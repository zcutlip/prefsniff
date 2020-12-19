#!/bin/sh -eu

DIRNAME="$(dirname $0)"

# set DISTRIBUTION_NAME variable
source "$DIRNAME"/projectname.sh

# utility functions
source "$DIRNAME"/functions.sh

generate_dist 3 || quit "Failed to generate dist"
