#!/bin/bash

ls /lwa/LineMonitoring/logs/*.gz | xargs -n1 /lwa/LineMonitoring/scripts/uploadLogfileLVM.py

