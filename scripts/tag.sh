#!/bin/sh -x

source "$(dirname $0)"/functions.sh

if ! branch_is_master;
then
    quit "Attempting to tag from branch $branch. Check out 'master' first." 1
fi



if ! branch_is_clean;
then
    echo "Tree contains uncommitted modifications:"
    git ls-files -m
    quit 1
fi

version=$(current_version);

if version_is_tagged "$version";
then
    echo "Version $version already tagged."
    git tag -l
    quit 1
fi

echo "Tagging version: $version"

git tag -a "v$version" -m "version $version" || quit "Failed to tag $version" $?

echo "Tags:"
git tag -l

quit "Done." 0
