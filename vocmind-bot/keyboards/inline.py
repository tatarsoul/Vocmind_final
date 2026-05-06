from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo


def _versioned_webapp_url(url: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["_v"] = "20260407-analytics1"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))



def main_menu(mini_app_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть кабинет", web_app=WebAppInfo(url=_versioned_webapp_url(mini_app_url)))],
        ]
    )
