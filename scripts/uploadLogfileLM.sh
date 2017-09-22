#!/bin/bash

ls /lwa/LineMonitoring/logs/*.gz | xargs -n1 ~ops/uploadLogfileLM.py

