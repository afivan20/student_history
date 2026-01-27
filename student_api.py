"""
Student API - Google Sheets Integration
Uses connection pooling and caching to prevent SSL exhaustion
"""
from services.google_sheets import get_sheets_manager


def student_history(student: str, use_cache: bool = True, cache_ttl: int = 300):
    """
    Get student lesson history from Google Sheets

    Args:
        student: Student name (worksheet name)
        use_cache: Whether to use caching (default: True)
        cache_ttl: Cache TTL in seconds (default: 300)

    Returns:
        List of batch_get results: [lessons_data, balance_data]

    Raises:
        Exception: If data cannot be fetched after retries
    """
    manager = get_sheets_manager()

    try:
        result = manager.get_student_history(
            worksheet_name=student.capitalize(),
            use_cache=use_cache,
            cache_ttl=cache_ttl
        )
        return result
    except Exception as e:
        print(f"Ошибка при получении данных из Google Sheets: {e}")
        print(f"Тип ошибки: {type(e).__name__}")
        import traceback
        traceback.print_exc()
        raise