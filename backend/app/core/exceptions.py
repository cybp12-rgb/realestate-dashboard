"""프로젝트 공통 예외. 단계별로 나눠 두면 로그·트러블슈팅에서 원인 구분이 쉽습니다."""


class PipelineError(Exception):
    """파이프라인 공통 상위 예외"""


class CollectError(PipelineError):
    """공공데이터 API 호출/응답 오류"""


class CleanError(PipelineError):
    """데이터 정제 단계 오류"""


class LLMError(PipelineError):
    """LLM API 호출 오류"""
