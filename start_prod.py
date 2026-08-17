#!/usr/bin/env python3
"""BorrowBuddy Production Server Launcher"""
import os
os.environ["BORROWBUDDY_ENV"] = "production"
os.environ["PORT"] = "7781"
os.environ["URL_PREFIX"] = "/BorrowBuddy"

from app import app
import ssl

context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(
    "/usr/local/AppCentral/httpd-2.4.43/data/certificate/server.crt",
    "/usr/local/AppCentral/httpd-2.4.43/data/certificate/server.key"
)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7781, ssl_context=context, debug=False)
