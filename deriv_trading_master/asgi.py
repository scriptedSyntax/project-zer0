import os, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'deriv_trading_master.settings')

# ✅ ADD THIS LINE TO INITIALIZE DJANGO PROPERLY
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from channels.auth import AuthMiddlewareStack
import analysis.routing

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            analysis.routing.websocket_urlpatterns
        )
    ),
})
# This file configures the ASGI application for the Django project.
# It sets up the routing for HTTP and WebSocket protocols, allowing the application to handle real-time WebSocket connections.