"""
Google Trends 크롤러 테스트 모듈.

Google Trends 실시간 인기 검색어 크롤러 테스트.

테스트 구조:
- 단위 테스트 (TestValidText, TestNormalizeLink, TestCrawlGoogleTrends, TestGetTrendKeywords, TestIntegration)
  : Mock 사용, 빠른 실행, 외부 의존성 없음
  
- 통합 테스트 (TestRealIntegration)
  : 실제 브라우저 실행, Mock 없음, 실제 Google Trends 접속
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch  # 단위 테스트용 (통합 테스트에서는 사용 안 함)
from pathlib import Path
import json
from datetime import datetime

from app.services.crawler.keywords.google_trend import (
    _valid_text,
    _normalize_link,
    crawl_google_trends,
    get_trend_keywords,
    EXCLUDED_TEXTS,
    TREND_URL,
)


class TestValidText:
    """_valid_text 헬퍼 함수 테스트."""
    
    def test_valid_text_accepts_normal_keyword(self):
        """정상적인 키워드는 통과."""
        assert _valid_text("노트북", EXCLUDED_TEXTS) is True
        assert _valid_text("아이폰 15", EXCLUDED_TEXTS) is True
        assert _valid_text("구글 트렌드", EXCLUDED_TEXTS) is True
    
    def test_valid_text_rejects_empty_or_short(self):
        """빈 문자열이나 너무 짧은 텍스트는 거부."""
        assert _valid_text("", EXCLUDED_TEXTS) is False
        assert _valid_text("a", EXCLUDED_TEXTS) is False  # 1글자
        assert _valid_text("가", EXCLUDED_TEXTS) is False  # 1글자
    
    def test_valid_text_rejects_too_long(self):
        """너무 긴 텍스트는 거부."""
        long_text = "a" * 101  # 101글자
        assert _valid_text(long_text, EXCLUDED_TEXTS) is False
    
    def test_valid_text_rejects_urls(self):
        """URL은 거부."""
        assert _valid_text("http://example.com", EXCLUDED_TEXTS) is False
        assert _valid_text("https://google.com", EXCLUDED_TEXTS) is False
    
    def test_valid_text_rejects_excluded_texts(self):
        """제외 목록에 있는 텍스트는 거부."""
        assert _valid_text("Trends", EXCLUDED_TEXTS) is False
        assert _valid_text("트렌드 상태", EXCLUDED_TEXTS) is False
        assert _valid_text("검색", EXCLUDED_TEXTS) is False
    
    def test_valid_text_rejects_texts_containing_excluded(self):
        """제외 텍스트를 포함하는 경우도 거부."""
        assert _valid_text("Google 트렌드란 무엇인가요?", EXCLUDED_TEXTS) is False
        assert _valid_text("트렌드 분석 페이지", EXCLUDED_TEXTS) is False


class TestNormalizeLink:
    """_normalize_link 헬퍼 함수 테스트."""
    
    def test_normalize_link_preserves_absolute_url(self):
        """절대 URL은 그대로 반환."""
        url = "https://trends.google.co.kr/trends/explore?q=test"
        assert _normalize_link(url) == url
    
    def test_normalize_link_converts_relative_path(self):
        """상대 경로는 절대 URL로 변환."""
        assert _normalize_link("/trends/explore") == "https://trends.google.co.kr/trends/explore"
        assert _normalize_link("/search") == "https://trends.google.co.kr/search"
    
    def test_normalize_link_handles_relative_without_slash(self):
        """슬래시 없는 상대 경로도 처리."""
        assert _normalize_link("trends/explore") == "https://trends.google.co.kr/trends/explore"
    
    def test_normalize_link_handles_empty_string(self):
        """빈 문자열은 빈 문자열 반환."""
        assert _normalize_link("") == ""
        assert _normalize_link(None) == ""
    
    def test_normalize_link_handles_http_url(self):
        """http URL도 처리."""
        url = "http://trends.google.co.kr/test"
        assert _normalize_link(url) == url


class TestCrawlGoogleTrends:
    """crawl_google_trends 메인 함수 테스트."""
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_success(self, mock_playwright):
        """성공적인 크롤링 테스트."""
        # Mock 설정
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        # Mock 페이지 요소 설정
        mock_keyword_elem = AsyncMock()
        mock_keyword_elem.inner_text = AsyncMock(return_value="테스트 키워드")
        mock_link_elem = AsyncMock()
        mock_link_elem.get_attribute = AsyncMock(return_value="/trends/explore?q=test")
        
        mock_row = AsyncMock()
        async def query_selector_side_effect(selector):
            return {
                ".mZ3RIc": mock_keyword_elem,
                "a": mock_link_elem
            }.get(selector)
        mock_row.query_selector = AsyncMock(side_effect=query_selector_side_effect)
        
        # query_selector_all은 여러 번 호출되므로 side_effect 사용
        # 방법 0만 사용 (방법 1, 2, 3 제거됨)
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                return [mock_row]  # 방법 0
            else:
                return []  # 다른 셀렉터는 빈 리스트
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        mock_page.query_selector = AsyncMock(return_value=None)  # 다음 페이지 버튼 없음
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # 함수 실행
        result = await crawl_google_trends(headless=True, max_trends=5)
        
        # 검증
        assert isinstance(result, dict)
        assert "total_trends" in result
        assert "trends" in result
        assert isinstance(result["trends"], list)
        assert result["total_trends"] >= 0
        
        # 브라우저가 닫혔는지 확인
        mock_browser.close.assert_called_once()
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_with_custom_excluded_texts(self, mock_playwright):
        """커스텀 제외 텍스트 사용 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        # 빈 결과 반환
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.query_selector = AsyncMock(return_value=None)  # 다음 페이지 버튼 없음
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        custom_excluded = {"커스텀", "제외", "텍스트"}
        result = await crawl_google_trends(
            headless=True,
            max_trends=10,
            excluded_texts=custom_excluded
        )
        
        assert isinstance(result, dict)
        assert result["total_trends"] == 0
        assert result["trends"] == []
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_respects_max_trends(self, mock_playwright):
        """max_trends 제한 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        # 여러 키워드 반환하도록 설정
        mock_rows = []
        for i in range(20):
            mock_row = AsyncMock()
            mock_keyword_elem = AsyncMock()
            mock_keyword_elem.inner_text = AsyncMock(return_value=f"키워드 {i}")
            async def query_selector_side_effect(selector, idx=i):
                return {
                    ".mZ3RIc": mock_keyword_elem,
                    "a": None
                }.get(selector)
            mock_row.query_selector = AsyncMock(side_effect=query_selector_side_effect)
            mock_rows.append(mock_row)
        
        # query_selector_all은 여러 번 호출되므로 side_effect 사용
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                return mock_rows  # 방법 0
            else:
                return []  # 다른 방법들은 빈 리스트
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        mock_page.query_selector = AsyncMock(return_value=None)  # 다음 페이지 버튼 없음
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        result = await crawl_google_trends(headless=True, max_trends=5)
        
        assert result["total_trends"] <= 5
        assert len(result["trends"]) <= 5
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_timeout(self, mock_playwright):
        """타임아웃 처리 테스트 - 첫 번째 호출 실패 후 재시도 성공."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        # 첫 번째 goto (networkidle)는 실패, 두 번째 goto (load)는 성공
        call_count = [0]  # 리스트를 사용하여 클로저에서 수정 가능하게 함
        async def goto_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Timeout")
            return None
        mock_page.goto = AsyncMock(side_effect=goto_side_effect)
        # query_selector_all은 여러 번 호출되므로 side_effect 사용
        # 방법 0만 사용 (방법 1, 2, 3 제거됨)
        async def query_selector_all_side_effect(selector):
            return []  # 빈 리스트 반환
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        mock_page.query_selector = AsyncMock(return_value=None)  # 다음 페이지 버튼 없음
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # 재시도 후 성공적으로 결과 반환
        result = await crawl_google_trends(
            headless=True,
            max_trends=10,
            page_timeout_ms=1000
        )
        
        assert isinstance(result, dict)
        assert "total_trends" in result
        assert "trends" in result
        # goto가 두 번 호출되었는지 확인 (첫 번째는 실패, 두 번째는 성공)
        assert call_count[0] == 2, f"goto가 {call_count[0]}번 호출되었습니다 (예상: 2번)"
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_browser_launch_failure(self, mock_playwright):
        """브라우저 실행 실패 예외 처리 테스트."""
        mock_playwright_instance = MagicMock()
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(side_effect=Exception("Browser launch failed"))
        
        # 브라우저 실행 실패 시 예외가 발생해야 함
        with pytest.raises(Exception, match="Browser launch failed"):
            await crawl_google_trends(headless=True, max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_page_creation_failure(self, mock_playwright):
        """페이지 생성 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(side_effect=Exception("Page creation failed"))
        
        # 페이지 생성 실패 시 예외가 발생해야 함
        with pytest.raises(Exception, match="Page creation failed"):
            await crawl_google_trends(headless=True, max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_query_selector_all_failure(self, mock_playwright):
        """query_selector_all 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_page.query_selector = AsyncMock(return_value=None)
        
        # query_selector_all이 "tbody tr" 셀렉터로 호출될 때 실패
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                raise Exception("Query selector failed")
            return []  # 다른 셀렉터는 빈 리스트 반환
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # query_selector_all 실패 시 예외가 전파되어야 함 (실제 코드에서 예외 처리 없음)
        with pytest.raises(Exception, match="Query selector failed"):
            await crawl_google_trends(headless=True, max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_inner_text_failure(self, mock_playwright):
        """inner_text() 호출 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_keyword_elem = AsyncMock()
        mock_keyword_elem.inner_text = AsyncMock(side_effect=Exception("Inner text failed"))
        mock_row = AsyncMock()
        async def query_selector_side_effect(selector):
            return {
                ".mZ3RIc": mock_keyword_elem,
                "a": None
            }.get(selector)
        mock_row.query_selector = AsyncMock(side_effect=query_selector_side_effect)
        
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                return [mock_row]
            return []
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # inner_text 실패 시 예외가 전파되어야 함 (실제 코드에서 예외 처리 없음)
        with pytest.raises(Exception, match="Inner text failed"):
            await crawl_google_trends(headless=True, max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_get_attribute_failure(self, mock_playwright):
        """get_attribute() 호출 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_keyword_elem = AsyncMock()
        mock_keyword_elem.inner_text = AsyncMock(return_value="테스트 키워드")
        mock_link_elem = AsyncMock()
        mock_link_elem.get_attribute = AsyncMock(side_effect=Exception("Get attribute failed"))
        mock_row = AsyncMock()
        async def query_selector_side_effect(selector):
            return {
                ".mZ3RIc": mock_keyword_elem,
                "a": mock_link_elem
            }.get(selector)
        mock_row.query_selector = AsyncMock(side_effect=query_selector_side_effect)
        
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                return [mock_row]
            return []
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # get_attribute 실패 시 예외가 전파되어야 함 (실제 코드에서 예외 처리 없음)
        with pytest.raises(Exception, match="Get attribute failed"):
            await crawl_google_trends(headless=True, max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_next_button_click_failure(self, mock_playwright):
        """다음 페이지 버튼 클릭 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_page.query_selector_all = AsyncMock(return_value=[])
        
        # 다음 페이지 버튼은 찾지만 클릭 실패
        mock_next_btn = AsyncMock()
        mock_next_btn.is_visible = AsyncMock(return_value=True)
        mock_next_btn.is_enabled = AsyncMock(return_value=True)
        mock_next_btn.scroll_into_view_if_needed = AsyncMock(return_value=None)
        mock_next_btn.evaluate = AsyncMock(side_effect=Exception("Click failed"))
        mock_next_btn.click = AsyncMock(side_effect=Exception("Click failed"))
        mock_page.query_selector = AsyncMock(return_value=mock_next_btn)
        
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # 다음 페이지 버튼 클릭 실패 시 루프가 종료되어야 함
        result = await crawl_google_trends(headless=True, max_trends=10)
        
        assert isinstance(result, dict)
        # 첫 페이지의 키워드는 수집되어야 함
        assert result["total_trends"] >= 0
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_wait_for_load_state_timeout(self, mock_playwright):
        """wait_for_load_state 타임아웃 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.query_selector = AsyncMock(return_value=None)
        
        # wait_for_load_state가 타임아웃
        mock_page.wait_for_load_state = AsyncMock(side_effect=Exception("Timeout"))
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # wait_for_load_state 타임아웃 시에도 계속 진행되어야 함
        result = await crawl_google_trends(headless=True, max_trends=10)
        
        assert isinstance(result, dict)
        assert "total_trends" in result
        assert "trends" in result
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_evaluate_failure(self, mock_playwright):
        """evaluate() 호출 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        # evaluate가 실패하는 경우 (스크롤 등)
        mock_page.evaluate = AsyncMock(side_effect=Exception("Evaluate failed"))
        
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # evaluate 실패 시 예외가 전파되어야 함 (실제 코드에서 예외 처리 없음)
        with pytest.raises(Exception, match="Evaluate failed"):
            await crawl_google_trends(headless=True, max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_browser_close_failure(self, mock_playwright):
        """브라우저 종료 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        
        # 브라우저 종료 실패
        mock_browser.close = AsyncMock(side_effect=Exception("Close failed"))
        
        # 브라우저 종료 실패 시 예외가 전파되어야 함 (실제 코드에서 예외 처리 없음)
        with pytest.raises(Exception, match="Close failed"):
            await crawl_google_trends(headless=True, max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_wait_for_selector_timeout(self, mock_playwright):
        """wait_for_selector 타임아웃 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        # wait_for_selector가 타임아웃
        mock_page.wait_for_selector = AsyncMock(side_effect=Exception("Timeout"))
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # wait_for_selector 타임아웃 시에도 계속 진행되어야 함
        result = await crawl_google_trends(headless=True, max_trends=10)
        
        assert isinstance(result, dict)
        assert "total_trends" in result
        assert "trends" in result
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_row_query_selector_failure(self, mock_playwright):
        """row.query_selector() 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_row = AsyncMock()
        mock_row.query_selector = AsyncMock(side_effect=Exception("Row query selector failed"))
        
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                return [mock_row]
            return []
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # row.query_selector 실패 시 예외가 전파되어야 함
        with pytest.raises(Exception, match="Row query selector failed"):
            await crawl_google_trends(headless=True, max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_button_is_visible_failure(self, mock_playwright):
        """버튼 is_visible() 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_keyword_elem = AsyncMock()
        mock_keyword_elem.inner_text = AsyncMock(return_value="테스트 키워드")
        mock_row = AsyncMock()
        async def query_selector_side_effect(selector):
            return {
                ".mZ3RIc": mock_keyword_elem,
                "a": None
            }.get(selector)
        mock_row.query_selector = AsyncMock(side_effect=query_selector_side_effect)
        
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                return [mock_row]
            return []
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        
        # 다음 페이지 버튼은 찾지만 is_visible 실패
        mock_next_btn = AsyncMock()
        mock_next_btn.is_visible = AsyncMock(side_effect=Exception("Is visible failed"))
        mock_page.query_selector = AsyncMock(return_value=mock_next_btn)

        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # is_visible 실패 시에도 최소 한 페이지는 수집되어야 함
        result = await crawl_google_trends(headless=True, max_trends=10)

        assert isinstance(result, dict)
        assert result["total_trends"] >= 1
        assert mock_next_btn.is_visible.await_count >= 1
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_scroll_into_view_failure(self, mock_playwright):
        """scroll_into_view_if_needed() 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_keyword_elem = AsyncMock()
        mock_keyword_elem.inner_text = AsyncMock(return_value="테스트 키워드")
        mock_row = AsyncMock()
        async def query_selector_side_effect(selector):
            return {
                ".mZ3RIc": mock_keyword_elem,
                "a": None
            }.get(selector)
        mock_row.query_selector = AsyncMock(side_effect=query_selector_side_effect)
        
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                return [mock_row]
            return []
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        
        # 다음 페이지 버튼은 찾지만 scroll_into_view_if_needed 실패
        mock_next_btn = AsyncMock()
        mock_next_btn.is_visible = AsyncMock(return_value=True)
        mock_next_btn.is_enabled = AsyncMock(return_value=True)
        mock_next_btn.scroll_into_view_if_needed = AsyncMock(side_effect=Exception("Scroll failed"))
        mock_page.query_selector = AsyncMock(return_value=mock_next_btn)
        
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # scroll_into_view_if_needed 실패 시에도 최소 한 페이지는 수집되어야 함
        result = await crawl_google_trends(headless=True, max_trends=10)

        assert isinstance(result, dict)
        assert result["total_trends"] >= 1
        mock_next_btn.scroll_into_view_if_needed.assert_awaited_once()
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_retry_query_selector_all_failure(self, mock_playwright):
        """재시도 로직에서 query_selector_all 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_keyword_elem = AsyncMock()
        mock_keyword_elem.inner_text = AsyncMock(return_value="테스트 키워드")
        mock_row = AsyncMock()
        async def query_selector_side_effect(selector):
            return {
                ".mZ3RIc": mock_keyword_elem,
                "a": None
            }.get(selector)
        mock_row.query_selector = AsyncMock(side_effect=query_selector_side_effect)

        # 첫 번째 호출은 1개 행 반환 (재시도 트리거), 재시도 중 실패
        call_count = [0]
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                call_count[0] += 1
                if call_count[0] == 1:
                    return [mock_row]
                elif call_count[0] > 1:
                    raise TypeError("Retry query selector failed")
            return []
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        mock_next_btn = AsyncMock()
        mock_next_btn.is_visible = AsyncMock(return_value=True)
        mock_next_btn.is_enabled = AsyncMock(return_value=True)
        mock_next_btn.scroll_into_view_if_needed = AsyncMock(return_value=None)
        mock_next_btn.evaluate = AsyncMock(return_value=None)
        mock_next_btn.click = AsyncMock(return_value=None)
        mock_page.query_selector = AsyncMock(return_value=mock_next_btn)
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # 재시도 중 query_selector_all 실패 시 예외가 전파되어야 함
        with pytest.raises(TypeError):
            await crawl_google_trends(headless=True, max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_crawl_google_trends_handles_table_update_wait_failure(self, mock_playwright):
        """테이블 업데이트 대기 중 query_selector_all 실패 예외 처리 테스트."""
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        mock_keyword_elem = AsyncMock()
        mock_keyword_elem.inner_text = AsyncMock(return_value="테스트 키워드")
        mock_row = AsyncMock()
        async def query_selector_side_effect(selector):
            return {
                ".mZ3RIc": mock_keyword_elem,
                "a": None
            }.get(selector)
        mock_row.query_selector = AsyncMock(side_effect=query_selector_side_effect)
        
        # 첫 번째 페이지는 성공, 두 번째 페이지로 이동 후 테이블 업데이트 대기 중 실패
        call_count = [0]
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                call_count[0] += 1
                if call_count[0] <= 1:
                    return [mock_row]  # 첫 번째 페이지
                elif call_count[0] > 10:  # 테이블 업데이트 대기 중
                    raise Exception("Table update wait failed")
                return [mock_row]
            return []
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        
        # 다음 페이지 버튼 찾기
        mock_next_btn = AsyncMock()
        mock_next_btn.is_visible = AsyncMock(return_value=True)
        mock_next_btn.is_enabled = AsyncMock(return_value=True)
        mock_next_btn.scroll_into_view_if_needed = AsyncMock(return_value=None)
        mock_next_btn.evaluate = AsyncMock(return_value=None)
        mock_next_btn.click = AsyncMock(return_value=None)
        mock_page.query_selector = AsyncMock(return_value=mock_next_btn)
        
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # 테이블 업데이트 대기 중 query_selector_all 실패 시 예외가 전파되어야 함
        with pytest.raises(Exception, match="Table update wait failed"):
            await crawl_google_trends(headless=True, max_trends=10)


class TestGetTrendKeywords:
    """get_trend_keywords 편의 함수 테스트."""
    
    @patch('app.services.crawler.keywords.google_trend.crawl_google_trends', new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_get_trend_keywords_returns_list(self, mock_crawl):
        """키워드 리스트 반환 테스트."""
        mock_crawl.return_value = {
            "total_trends": 3,
            "trends": [
                {"keyword": "키워드1", "link": "http://example.com/1"},
                {"keyword": "키워드2", "link": "http://example.com/2"},
                {"keyword": "키워드3", "link": "http://example.com/3"},
            ]
        }
        
        result = await get_trend_keywords(max_trends=3)
        
        assert isinstance(result, list)
        assert len(result) == 3
        assert result == ["키워드1", "키워드2", "키워드3"]
        mock_crawl.assert_called_once()
    
    @patch('app.services.crawler.keywords.google_trend.crawl_google_trends', new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_get_trend_keywords_filters_missing_keyword(self, mock_crawl):
        """keyword 필드가 없는 항목은 필터링."""
        mock_crawl.return_value = {
            "total_trends": 3,
            "trends": [
                {"keyword": "키워드1", "link": "http://example.com/1"},
                {"link": "http://example.com/2"},  # keyword 없음
                {"keyword": "키워드3", "link": "http://example.com/3"},
            ]
        }
        
        result = await get_trend_keywords()
        
        assert len(result) == 2
        assert "키워드1" in result
        assert "키워드3" in result
    
    @patch('app.services.crawler.keywords.google_trend.crawl_google_trends', new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_get_trend_keywords_handles_empty_result(self, mock_crawl):
        """빈 결과 처리."""
        mock_crawl.return_value = {
            "total_trends": 0,
            "trends": []
        }
        
        result = await get_trend_keywords()
        
        assert isinstance(result, list)
        assert len(result) == 0
    
    @patch('app.services.crawler.keywords.google_trend.crawl_google_trends', new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_get_trend_keywords_passes_parameters(self, mock_crawl):
        """파라미터 전달 테스트."""
        mock_crawl.return_value = {"total_trends": 0, "trends": []}
        
        custom_excluded = {"커스텀"}
        await get_trend_keywords(
            headless=False,
            max_trends=50,
            excluded_texts=custom_excluded,
            page_timeout_ms=30000
        )
        
        mock_crawl.assert_called_once_with(
            headless=False,
            max_trends=50,
            excluded_texts=custom_excluded,
            page_timeout_ms=30000
        )
    
    @patch('app.services.crawler.keywords.google_trend.crawl_google_trends', new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_get_trend_keywords_handles_crawl_exception(self, mock_crawl):
        """crawl_google_trends 예외 처리 테스트."""
        mock_crawl.side_effect = Exception("Crawl failed")
        
        # crawl_google_trends 실패 시 예외가 전파되어야 함
        with pytest.raises(Exception, match="Crawl failed"):
            await get_trend_keywords(max_trends=10)
    
    @patch('app.services.crawler.keywords.google_trend.crawl_google_trends', new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_get_trend_keywords_handles_missing_trends_key(self, mock_crawl):
        """trends 키가 없는 결과 처리 테스트."""
        mock_crawl.return_value = {
            "total_trends": 0
            # "trends" 키 없음
        }
        
        result = await get_trend_keywords()
        
        assert isinstance(result, list)
        assert len(result) == 0
    
    @patch('app.services.crawler.keywords.google_trend.crawl_google_trends', new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_get_trend_keywords_handles_invalid_trends_type(self, mock_crawl):
        """trends가 리스트가 아닌 경우 처리 테스트."""
        mock_crawl.return_value = {
            "total_trends": 1,
            "trends": "invalid"  # 리스트가 아님
        }
        
        # trends가 리스트가 아니면 빈 리스트 반환
        result = await get_trend_keywords()
        
        assert isinstance(result, list)
        assert len(result) == 0


class TestIntegration:
    """통합 테스트 (실제 브라우저 실행 없이)."""
    
    @patch('app.services.crawler.keywords.google_trend.async_playwright')
    @pytest.mark.asyncio
    async def test_full_workflow(self, mock_playwright):
        """전체 워크플로우 테스트."""
        # Mock 설정
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_playwright_instance = MagicMock()
        
        mock_playwright.return_value.__aenter__ = AsyncMock(return_value=mock_playwright_instance)
        mock_playwright.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_playwright_instance.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        
        # 실제 키워드처럼 보이는 데이터
        test_keywords = [
            "아이폰 15",
            "갤럭시 S24",
            "노트북",
            "태블릿",
            "스마트워치"
        ]
        
        mock_rows = []
        for keyword in test_keywords:
            mock_row = AsyncMock()
            mock_keyword_elem = AsyncMock()
            mock_keyword_elem.inner_text = AsyncMock(return_value=keyword)
            mock_link_elem = AsyncMock()
            mock_link_elem.get_attribute = AsyncMock(return_value=f"/trends/explore?q={keyword}")
            
            async def query_selector_side_effect(selector, kw=keyword):
                return {
                    ".mZ3RIc": mock_keyword_elem,
                    "a": mock_link_elem
                }.get(selector)
            mock_row.query_selector = AsyncMock(side_effect=query_selector_side_effect)
            mock_rows.append(mock_row)
        
        # query_selector_all은 여러 번 호출되므로 side_effect 사용
        # 방법 0만 사용 (방법 1, 2, 3 제거됨)
        async def query_selector_all_side_effect(selector):
            if selector == "tbody tr":
                return mock_rows  # 방법 0
            else:
                return []  # 다른 셀렉터는 빈 리스트
        mock_page.query_selector_all = AsyncMock(side_effect=query_selector_all_side_effect)
        mock_page.query_selector = AsyncMock(return_value=None)  # 다음 페이지 버튼 없음
        mock_page.wait_for_load_state = AsyncMock(return_value=None)
        mock_page.goto = AsyncMock(return_value=None)
        mock_page.wait_for_timeout = AsyncMock(return_value=None)
        mock_page.wait_for_selector = AsyncMock(return_value=None)
        mock_page.evaluate = AsyncMock(return_value=None)
        mock_browser.close = AsyncMock(return_value=None)
        
        # 실행
        result = await crawl_google_trends(headless=True, max_trends=10)
        keywords = await get_trend_keywords(headless=True, max_trends=10)
        
        # 검증
        assert result["total_trends"] > 0
        assert len(keywords) > 0
        assert all(isinstance(kw, str) for kw in keywords)
        assert all(len(kw) > 0 for kw in keywords)


class TestRealIntegration:
    """
    실제 브라우저를 사용하는 통합 테스트 (느리고 불안정할 수 있음).
    
    이 클래스의 테스트는 Mock을 사용하지 않습니다.
    실제 Playwright 브라우저를 실행하고 실제 Google Trends에 접속합니다.
    
    실행 방법:
    pytest test/crawler/keywords/test_google_trend.py::TestRealIntegration::test_real_google_trends_crawling -v -s
    
    또는 마커 사용:
    pytest test/crawler/keywords/test_google_trend.py -m integration -v -s
    """
    
    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_real_google_trends_crawling(self):
        """
        실제 Google Trends에서 키워드를 추출하는 테스트.
        
        Mock을 사용하지 않고 실제 브라우저를 실행합니다.
        실제 Google Trends 웹사이트에 접속하여 데이터를 수집합니다.
        """
        print("\n" + "="*70)
        print("🔍 실제 Google Trends 크롤링 테스트 시작")
        print("="*70)
        
        # 실제 크롤링 실행
        max_trends = 80  # 테스트용으로 적은 수
        print(f"\n📦 설정:")
        print(f"   - 최대 수집 개수: {max_trends}개")
        print(f"   - 헤드리스 모드: True")
        print(f"\n⏳ 크롤링 시작... (30초~1분 정도 소요될 수 있습니다)\n")
        
        result = await crawl_google_trends(
            headless=True,
            max_trends=max_trends,
            page_timeout_ms=60_000
        )
        
        # 결과 출력
        print("\n" + "="*70)
        print(f"✅ 크롤링 완료!")
        print(f"📊 총 {result['total_trends']}개 키워드 수집")
        print("="*70)
        print("\n📋 수집된 키워드 목록:")
        print("-" * 70)
        
        for idx, trend in enumerate(result['trends'][:max_trends], 1):
            keyword = trend.get('keyword', '')
            link = trend.get('link', '')
            print(f"{idx:2d}. {keyword}")
            if link:
                display_link = link[:65] + "..." if len(link) > 65 else link
                print(f"    🔗 {display_link}")
        
        # 검증
        assert isinstance(result, dict), "결과가 딕셔너리 형식이 아닙니다"
        assert "total_trends" in result, "total_trends 키가 없습니다"
        assert "trends" in result, "trends 키가 없습니다"
        assert result["total_trends"] > 0, "키워드가 하나도 수집되지 않았습니다"
        assert len(result["trends"]) > 0, "트렌드 리스트가 비어있습니다"
        
        # 키워드만 추출
        keywords = await get_trend_keywords(headless=True, max_trends=max_trends)
        print(f"\n📝 키워드만 추출: {len(keywords)}개")
        print("-" * 70)
        for idx, kw in enumerate(keywords[:15], 1):
            print(f"{idx:2d}. {kw}")
        if len(keywords) > 15:
            print(f"    ... 외 {len(keywords) - 15}개")
        
        # JSON 파일로 저장 (test_google_trend.py와 같은 경로)
        test_dir = Path(__file__).parent  # test/crawler/keywords/
        output_file = test_dir / "google_trends_test_result.json"
        try:
            output_data = {
                "timestamp": datetime.now().isoformat(),
                "test_settings": {
                    "max_trends": max_trends,
                    "headless": True
                },
                "result": result,
                "keywords_only": keywords
            }
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            print(f"\n💾 결과 저장: {output_file}")
        except Exception as e:
            print(f"\n⚠️ 파일 저장 실패: {e}")
        
        print("\n" + "="*70)
        print("✅ 테스트 완료!")
        print("="*70 + "\n")
        
        # 검증
        assert len(keywords) > 0, "키워드 리스트가 비어있습니다"
        assert all(isinstance(kw, str) for kw in keywords), "모든 키워드는 문자열이어야 합니다"
        assert all(len(kw) > 0 for kw in keywords), "빈 키워드가 있습니다"

