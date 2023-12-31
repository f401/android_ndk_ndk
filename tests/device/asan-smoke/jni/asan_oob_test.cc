//===-- asan_oob_test.cc --------------------------------------------------===//
//
//                     The LLVM Compiler Infrastructure
//
// This file is distributed under the University of Illinois Open Source
// License. See LICENSE.TXT for details.
//
//===----------------------------------------------------------------------===//
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include <string>

#include <gtest/gtest.h>

#if __LP64__ || defined(_WIN64)
#  define SANITIZER_WORDSIZE 64
#else
#  define SANITIZER_WORDSIZE 32
#endif

#define NOINLINE __attribute__((noinline))

typedef uint8_t   U1;
typedef uint16_t  U2;
typedef uint32_t  U4;
typedef uint64_t  U8;

const size_t kLargeMalloc = 1 << 24;

// Make the compiler thinks that something is going on there.
inline void break_optimization(void *arg) {
#if !defined(_WIN32) || defined(__clang__)
  __asm__ __volatile__("" : : "r" (arg) : "memory");
#endif
}

// This function returns its parameter but in such a way that compiler
// can not prove it.
template<class T>
NOINLINE
static T Ident(T t) {
  T ret = t;
  break_optimization(&ret);
  return ret;
}

NOINLINE void *malloc_fff(size_t size) {
  void *res = malloc/**/(size); break_optimization(0); return res;}
NOINLINE void *malloc_eee(size_t size) {
  void *res = malloc_fff(size); break_optimization(0); return res;}
NOINLINE void *malloc_ddd(size_t size) {
  void *res = malloc_eee(size); break_optimization(0); return res;}
NOINLINE void *malloc_ccc(size_t size) {
  void *res = malloc_ddd(size); break_optimization(0); return res;}
NOINLINE void *malloc_bbb(size_t size) {
  void *res = malloc_ccc(size); break_optimization(0); return res;}
NOINLINE void *malloc_aaa(size_t size) {
  void *res = malloc_bbb(size); break_optimization(0); return res;}

NOINLINE void free_ccc(void *p) { free(p); break_optimization(0);}
NOINLINE void free_bbb(void *p) { free_ccc(p); break_optimization(0);}
NOINLINE void free_aaa(void *p) { free_bbb(p); break_optimization(0);}

template<typename T>
NOINLINE void asan_write(T *a) {
  *a = 0;
}

NOINLINE void asan_write_sized_aligned(uint8_t *p, size_t size) {
  EXPECT_EQ(0U, ((uintptr_t)p % size));
  if      (size == 1) asan_write((uint8_t*)p);
  else if (size == 2) asan_write((uint16_t*)p);
  else if (size == 4) asan_write((uint32_t*)p);
  else if (size == 8) asan_write((uint64_t*)p);
}

template<typename T>
NOINLINE void oob_test(int size, int off) {
  char *p = (char*)malloc_aaa(size);
  // fprintf(stderr, "writing %d byte(s) into [%p,%p) with offset %d\n",
  //        sizeof(T), p, p + size, off);
  asan_write((T*)(p + off));
  free_aaa(p);
}

static std::string GetLeftOOBMessage(int off) {
  char str[100];
  sprintf(str, "is located.*%d byte.*before", off);
  return str;
}

static std::string GetRightOOBMessage(int off) {
  char str[100];
#if !defined(_WIN32)
  // FIXME: Fix PR42868 and remove SEGV match.
  sprintf(str, "is located.*%d byte.*after|SEGV", off);
#else
  // `|` doesn't work in googletest's regexes on Windows,
  // see googletest/docs/advanced.md#regular-expression-syntax
  // But it's not needed on Windows anyways.
  sprintf(str, "is located.*%d byte.*after", off);
#endif
  return str;
}

template<typename T>
void OOBTest() {
  for (int size = sizeof(T); size < 20; size += 5) {
    for (int i = -5; i < 0; i++)
      EXPECT_DEATH(oob_test<T>(size, i), GetLeftOOBMessage(-i));

    for (int i = 0; i < (int)(size - sizeof(T) + 1); i++)
      oob_test<T>(size, i);

    for (int i = size - sizeof(T) + 1; i <= (int)(size + 2 * sizeof(T)); i++) {
      // we don't catch unaligned partially OOB accesses.
      if (i % sizeof(T)) continue;
      int off = i >= size ? (i - size) : 0;
      EXPECT_DEATH(oob_test<T>(size, i), GetRightOOBMessage(off));
    }
  }

  EXPECT_DEATH(oob_test<T>(kLargeMalloc, -1), GetLeftOOBMessage(1));
  EXPECT_DEATH(oob_test<T>(kLargeMalloc, kLargeMalloc), GetRightOOBMessage(0));
}

// TODO(glider): the following tests are EXTREMELY slow on Darwin:
//   AddressSanitizer.OOB_char (125503 ms)
//   AddressSanitizer.OOB_int (126890 ms)
//   AddressSanitizer.OOBRightTest (315605 ms)
//   AddressSanitizer.SimpleStackTest (366559 ms)

TEST(AddressSanitizer, OOB_char) {
  OOBTest<U1>();
}

TEST(AddressSanitizer, OOB_int) {
  OOBTest<U4>();
}

TEST(AddressSanitizer, OOBRightTest) {
  size_t max_access_size = SANITIZER_WORDSIZE == 64 ? 8 : 4;
  for (size_t access_size = 1; access_size <= max_access_size;
       access_size *= 2) {
    for (size_t alloc_size = 1; alloc_size <= 8; alloc_size++) {
      for (size_t offset = 0; offset <= 8; offset += access_size) {
        void *p = malloc(alloc_size);
        // allocated: [p, p + alloc_size)
        // accessed:  [p + offset, p + offset + access_size)
        uint8_t *addr = (uint8_t*)p + offset;
        if (offset + access_size <= alloc_size) {
          asan_write_sized_aligned(addr, access_size);
        } else {
          int outside_bytes = offset > alloc_size ? (offset - alloc_size) : 0;
          EXPECT_DEATH(asan_write_sized_aligned(addr, access_size),
                       GetRightOOBMessage(outside_bytes));
        }
        free(p);
      }
    }
  }
}

TEST(AddressSanitizer, LargeOOBRightTest) {
  size_t large_power_of_two = 1 << 19;
  for (size_t i = 16; i <= 256; i *= 2) {
    size_t size = large_power_of_two - i;
    char *p = Ident(new char[size]);
    EXPECT_DEATH(p[size] = 0, GetRightOOBMessage(0));
    delete [] p;
  }
}

TEST(AddressSanitizer, DISABLED_DemoOOBLeftLow) {
  oob_test<U1>(10, -1);
}

TEST(AddressSanitizer, DISABLED_DemoOOBLeftHigh) {
  oob_test<U1>(kLargeMalloc, -1);
}

TEST(AddressSanitizer, DISABLED_DemoOOBRightLow) {
  oob_test<U1>(10, 10);
}

TEST(AddressSanitizer, DISABLED_DemoOOBRightHigh) {
  oob_test<U1>(kLargeMalloc, kLargeMalloc);
}
