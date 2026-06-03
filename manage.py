#!/usr/bin/env python
import os
import sys


def main() -> None:
	os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
	
	# Load .env file if it exists
	try:
		from dotenv import load_dotenv
		from pathlib import Path
		env_path = Path(__file__).resolve().parent / '.env'
		if env_path.exists():
			load_dotenv(env_path)
	except ImportError:
		pass  # dotenv not installed, rely on system environment variables
	
	from django.core.management import execute_from_command_line
	execute_from_command_line(sys.argv)


if __name__ == "__main__":
	main()
