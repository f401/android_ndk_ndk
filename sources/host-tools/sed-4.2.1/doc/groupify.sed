#! /bin/sed -nf
# Script to add @group...@end group tags to sed.texi.in
# so that comments are not separated from the instructions
# that they refer to.

# Step 1: search for the conventional "@c start----" comment
1a\
@c Do not edit this file!! It is automatically generated from sed-in.texi.
p
/^@c start-*$/! b

# Step 2: loop until we find a @ command
:a
n
p
/^@/! ba

# Step 3: process everything until a "@end" command

# Step 3.1: Print the blank lines before the group.  If we reach the "@end",
#           we go back to step 1.
:b
n
/^@end/ {
  p
  b
}
/^[ 	]*$/ {
  p
  bb
}

# Step 3.2: Add to hold space every line until an empty one or "@end"
h
:c
n
/^@end example/! {
  /^[ 	]*$/! {
    H
    bc
  }
}

# Step 3.3: Working in hold space, add @group...@end group if there are
#           at least two lines.  Then print the lines we processed and
#	    switch back to pattern space.
x
/\n/ {
  s/.*/@group\
&\
@end group/
}
p

# Step 3.4: Switch back to pattern space, print the first blank line
#           and possibly go back to step 3.1
x
p
/^@end/ !bb
