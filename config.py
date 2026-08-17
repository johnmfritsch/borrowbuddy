"""
BorrowBuddy Configuration
Supports both production and development environments
"""
import os

class Config:
    """Base configuration"""
    # Determine base directory dynamically
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # Environment (default to production)
    ENV = os.environ.get("BORROWBUDDY_ENV", "production")
    
    # Database configuration
    DATABASE = os.path.join(BASE_DIR, "data", "borrowbuddy.db")
    
    # Upload folder for photos
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "images")
    
    # URL prefix for routing
    URL_PREFIX = os.environ.get("URL_PREFIX", "/BorrowBuddy")
    
    # Flask settings
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    
    # Server settings
    HOST = "0.0.0.0"
    PORT = int(os.environ.get("PORT", 7781))
    DEBUG = False
    
    # SSL Certificate paths (for NAS)
    SSL_CERT = "/usr/local/AppCentral/httpd-2.4.43/data/certificate/server.crt"
    SSL_KEY = "/usr/local/AppCentral/httpd-2.4.43/data/certificate/server.key"
    
    @staticmethod
    def get_config():
        """Return configuration based on environment"""
        env = os.environ.get("BORROWBUDDY_ENV", "production")
        if env == "development":
            return DevelopmentConfig()
        return ProductionConfig()

class ProductionConfig(Config):
    """Production configuration"""
    ENV = "production"
    DEBUG = False
    URL_PREFIX = "/BorrowBuddy"
    PORT = 7781

class DevelopmentConfig(Config):
    """Development configuration"""
    ENV = "development"
    DEBUG = True
    URL_PREFIX = "/BorrowBuddy_dev"
    PORT = 7782
    
    # Use separate dev database
    DATABASE = os.path.join(Config.BASE_DIR, "data", "borrowbuddy_dev.db")
