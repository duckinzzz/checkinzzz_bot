def normalize_name(value: str) -> str:
    """Ключ сверки ФИО: регистр, ё и любые пробелы не важны."""
    lowered = value.replace("ё", "е").replace("Ё", "Е").lower()
    return " ".join(lowered.split())
