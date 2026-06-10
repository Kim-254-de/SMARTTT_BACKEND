from .base import *  # noqa: F403,F401
import os

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# Inherits PostgreSQL configuration from base.py
