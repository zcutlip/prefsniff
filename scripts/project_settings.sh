# shellcheck shell=sh
# shellcheck disable=SC2034
# if this is used it should be copied to the project's directory next to
# the symlinks/copies of these repo management scripts, and renamed to project_settings.sh
# e.g., project/scripts/project_settings.sh

# if python3 ./setup.py --name produces the wrong PyPI distribution name
# you maybe override it, setting the proper name here
DISTRIBUTION_NAME="prefsniff"

# for python projects, if the root package is named differently
# than the project/distribution name, override that here
# e.g., mock-op vs mock_op
# This will get used for scripts that try to locate files *within* the project
# e.g., mock_op/__about__.py
# ROOT_PACKAGE_NAME="prefsniff"

# Either don't set, or set to "1" to enable
# if set at all and not set to "1" twine upload will not happen
TWINE_UPLOAD_ENABLED="1"
