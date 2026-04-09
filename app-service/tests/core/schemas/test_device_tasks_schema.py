from core.schemas.device_tasks import ResultArray


def test_result_array_normalizes_string_result():
    result = ResultArray.model_validate(
        {
            "id": 1,
            "ext_id": 10,
            "status_code": 200,
            "result": "plain text",
        }
    )

    assert result.result == {"value": "plain text"}


def test_result_array_normalizes_integer_result():
    result = ResultArray.model_validate(
        {
            "id": 1,
            "ext_id": 10,
            "status_code": 200,
            "result": 123,
        }
    )

    assert result.result == {"value": 123}


def test_result_array_keeps_none_result():
    result = ResultArray.model_validate(
        {
            "id": 1,
            "ext_id": 10,
            "status_code": 200,
            "result": None,
        }
    )

    assert result.result is None

