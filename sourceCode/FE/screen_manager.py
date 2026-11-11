from kivy.uix.screenmanager import ScreenManager, NoTransition

from auth_screen import AuthScreen
from calendar_screen import CalendarHomeScreen
from chat_screen import ChatAssistantScreen
from search_screen import SearchScreen


class AppScreenManager(ScreenManager):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.transition = NoTransition()

        self.add_widget(AuthScreen(name="login"))
        self.add_widget(CalendarHomeScreen(name="calendar_home"))
        self.add_widget(SearchScreen(name="search_home"))
        self.add_widget(ChatAssistantScreen(name="chat_home"))

        self.current = "login"