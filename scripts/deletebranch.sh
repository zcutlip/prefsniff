#!/bin/sh

# File: deletebranch.sh
# Author: Zachary Cutlip <uid000@gmail.com>
# Purpose: (Relatively) safely delete specified branch from local and origin in one pass

quit(){
    if [ $# -gt 1 ];
    then
        echo $1
        shift
    fi
    exit $1
}

local_branch_exists() {
    local branch="$1"
    git branch | grep "[:space:]*$branch$"
    return $?
}

remote_branch_exists() {
    local remote="$1"
    local branch="$2"
    local remote_string="remotes\/$remote\/$branch"
    git branch -a | grep "[:space:]*$remote_string$"
    return $?
}

is_current_branch() {
    local to_delete="$1"
    local branch=$(git rev-parse --abbrev-ref HEAD)
    [ "$to_delete" = "$branch" ]
    return $?
}

merged() {
    local to_delete="$1"
    local commit=$(git log $to_delete | head -1)
    git log | grep "$commit";
    return $?
}

remote_merged() {
    local remote="$1"
    local to_delete="$2"
    local remote_string="remotes/$remote/$to_delete"
    local commit=$(git log $remote_string | head -1)
    git log | grep "$commit";
    return $?
}

to_delete=$1
remote="origin"
if [ $# -gt 1 ];
then
    remote="$2"
fi

if [ -z "$to_delete" ];
then
    quit "Specify a branch to delete" 1
fi

if is_current_branch "$to_delete";
then
    quit "Can't delete current branch: $branch" 1
fi

if [ "$to_delete" = "master" ];
then
    quit "Refusing to delete master branch." 1
fi

local_exists=0
remote_exists=0
if local_branch_exists "$to_delete";
then
    local_exists=1
fi
if remote_branch_exists "$remote" "$to_delete";
then
    remote_exists=1
fi

if [ $local_exists -eq 0 ] && [ $remote_exists -eq 0 ];
then
    quit "Neither local nor remote branch exists" 1
fi

if [ $local_exists -gt 0 ];
then
    if ! merged "$to_delete";
    then
        quit "Branch $to_delete appears not to be merged." 1
    fi
elif [ $remote_exists -gt 0 ];
then
    if ! remote_merged "$remote" "$to_delete";
    then
        quit "Remote branch $to_delete appears not to be merged." 1
    fi
fi

echo "Deleting branch $to_delete from local and $remote."

git push -d $remote "$to_delete"
ret1=$?
git branch -d "$to_delete"
ret2=$?

[ $ret1 -eq 0 ] || [ $ret2 -eq 0 ]
quit $?
