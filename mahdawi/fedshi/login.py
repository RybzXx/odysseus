"""
fedshi.login — run once to sign in. You perform the OTP; code saves the session.

Usage: python -m fedshi.login

Opens a headed browser at the Fedshi login page. Enter your phone number and the
OTP yourself. When the dashboard loads, the session state is saved and later
extractions run headlessly (spec 2.3.1).
"""
import sys

from mahdawi.fedshi import session


def main() -> int:
    from mahdawi.fedshi.playwright_engine import PlaywrightFedshiSource
    print("Opening Fedshi login. Complete the OTP in the browser window...")
    path = PlaywrightFedshiSource().login()
    print("Session saved to %s" % path)
    print("Has state:", session.has_state())
    return 0


if __name__ == "__main__":
    sys.exit(main())
