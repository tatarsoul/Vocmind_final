from aiogram.fsm.state import State, StatesGroup


class ActivateKeyState(StatesGroup):
    waiting_for_key = State()