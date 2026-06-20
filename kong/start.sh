#!/bin/bash
set -e

# Write declarative config string to file if provided
if [ -n "$KONG_DECLARATIVE_CONFIG_STRING" ]; then
    echo "$KONG_DECLARATIVE_CONFIG_STRING" > /kong/kong.yaml
    export KONG_DECLARATIVE_CONFIG=/kong/kong.yaml
    unset KONG_DECLARATIVE_CONFIG_STRING
    echo "Kong config written to /kong/kong.yaml ($(wc -c < /kong/kong.yaml) bytes)"
fi

exec kong start --vv
