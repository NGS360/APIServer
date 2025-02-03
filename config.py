''' Application Config profiles '''
import os

class DefaultConfig: # pylint: disable=too-few-public-methods
    ''' Default Config profile '''
    APP_NAME = os.environ.get("APP_NAME", "NGS360")
