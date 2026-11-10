mc alias set local http://silo:9000 $SILO_ROOT_USER $SILO_ROOT_PASSWORD >/dev/null
mc rm --recursive --force local/$SILO_BUCKET >/dev/null 2>&1
echo "OBJECTS_LEFT=$(mc ls --recursive local/$SILO_BUCKET | wc -l)"
echo SILO-CLEANED
