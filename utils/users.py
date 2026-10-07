from aiogram import types


def get_user_name(user: types.User | None) -> str:
    if user is None:
        return "unknown"
    if user.username:
        return f"@{user.username}"
    return f"{user.first_name or user.id}"
