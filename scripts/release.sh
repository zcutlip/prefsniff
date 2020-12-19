#!/bin/sh -x
DIRNAME="$(dirname $0)"

# set DISTRIBUTION_NAME variable
source "$DIRNAME"/projectname.sh

# utility functions
source "$DIRNAME"/functions.sh

if ! branch_is_master;
then
    quit "Checkout branch 'master' before generating release." 1
fi

if ! branch_is_clean;
then
    echo "Tree contains uncommitted modifications:"
    git ls-files -m
    quit 1
fi
version=$(current_version);

if ! version_is_tagged "$version";
then
    echo "Current version $version isn't tagged."
    echo "Attempting to tag..."
    "$DIRNAME"/tag.sh || quit "Failed to tag a release." 1
fi

generate_dist(){
    python3 setup.py sdist bdist_wheel || quit "Failed to generate source & binary distributions." 1
}

version=$(current_version);

generate_dist;
echo "About to post the following distribution files to pypi.org."
ls -1 dist/"$DISTRIBUTION_NAME"-$version.*

if prompt_yes_no;
then
    python3 -m twine upload dist/"$DISTRIBUTION_NAME"-$version*
fi

