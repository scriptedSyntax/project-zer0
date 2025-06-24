# analysis/routing.py
from django.urls import re_path
from .consumers import AnalysisConsumer
from .bot_consumer import BotConsumer

websocket_urlpatterns = [
    re_path(r'wss/analysis/$', AnalysisConsumer.as_asgi()),
    re_path(r'wss/bot/$', BotConsumer.as_asgi()), # Bot WebSocket for real-time bot control
]
# This file defines the routing for WebSocket connections in the analysis app.
# It maps the WebSocket URL to the AnalysisConsumer, which handles real-time analysis updates.