# main.py

import os
os.environ['AUTOWRAPT_BOOTSTRAP'] = 'instrumentation'

import mypackage.simple_module
print(mypackage.simple_module.greet("Alice"))
