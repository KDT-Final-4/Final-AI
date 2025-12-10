"""
Google Trends 실시간 인기 검색어 크롤러.

Playwright를 사용해 한국(KR) 실시간 트렌드 페이지에서 키워드와 링크를 수집한다.
"""

from __future__ import annotations

import asyncio
import requests
import logging
from typing import Dict, List, Optional, Set
from app.config import JAVA_SERVER_ADDRESS
from app.logs import log_info, log_error

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

TREND_URL = "https://trends.google.co.kr/trending?geo=KR"
EXCLUDED_TEXTS: Set[str] = {
    "Trends",
    "트렌드 상태",
    "트렌드 분석",
    "검색",
    "탐색",
    "실시간 인기",
    "홈",
    "전 세계",
    "지금",
    "에서 무엇을 검색하고 있는지 알아보세요",
    "검색 관심도",
    "지난 24시간",
    "이(가) 인기 있는 이유는 무엇일까요?",
    "상세 데이터 검토",
    "트렌드 데이터팀",
    "선별한 문제와 이벤트",
    "트렌드 활용법",
    "언론사",
    "자선단체",
    "전 세계에서",
    "Google 트렌드를 어떻게 사용하고 있는지",
    "확인해보세요",
    "Google 트렌드란 무엇인가요?",
    "Google 트렌드의 기본사항",
    "데이터에 관해 알아보기",
    "로그인",
    "개인정보처리방침",
    "고급 Google 트렌드",
    "도움말",
    "의견 보내기",
}


def _valid_text(text: str, excluded_texts: Set[str]) -> bool:
    """UI 문구를 제외하고 키워드 후보만 남긴다."""
    if not text or len(text) < 2 or len(text) > 100:
        return False
    if text.startswith("http"):
        return False
    if text in excluded_texts:
        return False
    if any(ex in text for ex in excluded_texts):
        return False
    return True


def _normalize_link(href: Optional[str]) -> str:
    """상대 경로를 절대 URL로 정규화."""
    if not href:
        return ""
    href = href.strip()
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"https://trends.google.co.kr{href}"
    return f"https://trends.google.co.kr/{href}"


async def crawl_google_trends(
    *,
    headless: bool = True,
    max_trends: int = 80,
    excluded_texts: Optional[Set[str]] = None,
    page_timeout_ms: int = 60_000,
) -> Dict[str, object]:
    """
    구글 트렌드 실시간 인기 검색어를 크롤링한다.

    Returns:
        dict: {"total_trends": int, "trends": [{"keyword": str, "link": str}, ...]}
    """
    excluded = excluded_texts or EXCLUDED_TEXTS
    trends: List[Dict[str, str]] = []
    found: Set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()
        # logger.info("Google Trends 접속: %s", TREND_URL)

        try:
            print("entering google trend...")
            await page.goto(
                TREND_URL, wait_until="networkidle", timeout=page_timeout_ms
            )
            print("ok")
        except Exception:
            # logger.warning("초기 접속 실패, load 이벤트까지 대기 재시도")
            print("can't enter google trend")
            await page.goto(TREND_URL, wait_until="load", timeout=page_timeout_ms)

        # 동적 로딩 대기
        print("waiting timeout...")
        await page.wait_for_timeout(8_000)
        print("ok")

        # 트렌드 섹션 렌더링 대기
        try:
            print("waiting selector...")
            await page.wait_for_selector(
                "c-wiz, [jsname], [jscontroller]", timeout=20_000
            )
            print("ok")
        except Exception:
            # logger.debug("트렌드 섹션 selector 대기 타임아웃")
            print("timeout!")
        await page.wait_for_timeout(5_000)

        # 추가 로드를 위해 스크롤
        print("waiting scrolls...")
        for idx in range(20):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(2_000)
            if idx % 5 == 0:
                await page.wait_for_timeout(3_000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(3_000)
        print("ok")

        # 방법 0: 테이블 기반 페이지 네비게이션
        print("waiting page navigation")
        await page.wait_for_timeout(1_000)
        paged_round = 0
        previous_first_keyword = None
        previous_page_keywords: Set[str] = set()
        logger.info("방법 0: 테이블 기반 페이지 네비게이션 시작")
        
        while len(trends) < max_trends:
            paged_round += 1
            logger.debug("페이지 라운드 %s 시작", paged_round)
            
            if paged_round > 20:
                logger.debug("최대 페이지 라운드(20) 도달, 방법 0 종료")
                break
            
            # 테이블이 로드될 때까지 명시적으로 대기
            try:
                await page.wait_for_selector("tbody tr", timeout=10_000)
                await page.wait_for_timeout(1_000)  # 추가 대기
            except Exception:
                pass
            
            # 현재 페이지의 트렌드 수집 (재시도 로직 포함)
            rows = await page.query_selector_all("tbody tr")
            
            # 행이 너무 적으면 (1개 이하) 테이블이 완전히 로드되지 않았을 수 있음
            if len(rows) <= 1 and paged_round > 1:
                logger.debug("라운드 %s: 행이 %s개만 발견됨, 테이블 로드 대기 중...", paged_round, len(rows))
                # 추가 대기 및 재시도
                for retry in range(5):
                    await page.wait_for_timeout(1_000)
                    rows = await page.query_selector_all("tbody tr")
                    if len(rows) > 1:
                        logger.debug("라운드 %s: 재시도 성공 - %s개 행 발견", paged_round, len(rows))
                        break
                    if retry == 4:
                        logger.debug("라운드 %s: 재시도 실패 - %s개 행만 발견", paged_round, len(rows))
            
            logger.debug("현재 페이지에서 %s개 행 발견", len(rows))
            
            if not rows:
                logger.debug("라운드 %s: 행이 없어 종료", paged_round)
                break
            
            # 행이 1개만 있고 이전 라운드에서도 수집이 안 되었다면 종료
            if len(rows) == 1 and paged_round > 1:
                first_row = rows[0]
                keyword_elem = await first_row.query_selector(".mZ3RIc")
                if keyword_elem:
                    test_keyword = (await keyword_elem.inner_text() or "").strip()
                    if test_keyword in found:
                        logger.debug("라운드 %s: 중복 키워드만 발견, 종료", paged_round)
                        break
            
            # 현재 페이지의 첫 번째 키워드 확인 (페이지 변경 여부 검증)
            current_first_keyword = None
            current_page_keywords: Set[str] = set()
            
            for row in rows:
                keyword_elem = await row.query_selector(".mZ3RIc")
                if keyword_elem:
                    keyword_text = (await keyword_elem.inner_text() or "").strip()
                    if keyword_text:
                        current_page_keywords.add(keyword_text)
                        if current_first_keyword is None:
                            current_first_keyword = keyword_text
            
            # 페이지가 변경되지 않았는지 확인
            if previous_first_keyword:
                if current_first_keyword == previous_first_keyword:
                    logger.debug("첫 번째 키워드 동일: %s", current_first_keyword)
                    if current_page_keywords == previous_page_keywords:
                        logger.debug("페이지 내용이 완전히 동일함 (중복 키워드: %s개), 종료", len(current_page_keywords))
                        break
                    else:
                        new_keywords = current_page_keywords - previous_page_keywords
                        if len(new_keywords) > 0:
                            logger.debug("첫 번째 키워드는 같지만 새로운 키워드 %s개 발견, 계속 진행", len(new_keywords))
                        else:
                            logger.debug("첫 번째 키워드는 같고 새로운 키워드 없음, 종료")
                            break
            
            previous_first_keyword = current_first_keyword
            previous_page_keywords = current_page_keywords.copy()
            
            new_items = 0
            for row in rows:
                keyword_elem = await row.query_selector(".mZ3RIc")
                if not keyword_elem:
                    continue
                text = (await keyword_elem.inner_text() or "").strip()
                if not _valid_text(text, excluded) or text in found:
                    continue
                link_url = ""
                link_elem = await row.query_selector("a")
                if link_elem:
                    href = await link_elem.get_attribute("href")
                    link_url = _normalize_link(href)
                found.add(text)
                trends.append({"keyword": text, "link": link_url})
                new_items += 1
                if len(trends) >= max_trends:
                    break
            
            logger.debug("현재 라운드에서 %s개 새 항목 수집 (총 %s개)", new_items, len(trends))
            
            if len(trends) >= max_trends:
                logger.info("목표 개수(%s) 도달, 방법 0 종료", max_trends)
                break
            
            if new_items == 0:
                logger.debug("새 항목이 없어 방법 0 종료")
                break
            
            # 다음 페이지 버튼 찾기
            next_btn = None
            next_button_selectors = [
                "button[jsname='ViaHrd']",
                "[jsname='ViaHrd']",
                ".enOdEe-wZVHId-gruSEe .enOdEe-wZVHId-gruSEe-UbuQg .enOdEe-wZVHId-gruSEe-yXBf7b button[jsname='ViaHrd']",
                ".enOdEe-wZVHId-gruSEe .enOdEe-wZVHId-gruSEe-UbuQg .enOdEe-wZVHId-gruSEe-yXBf7b span button[jsname='ViaHrd']",
                ".enOdEe-wZVHId-gruSEe .enOdEe-wZVHId-gruSEe-UbuQg .enOdEe-wZVHId-gruSEe-yXBf7b button[aria-label='다음 페이지로 이동']",
                "button.enOdEe-wZVHId-gruSEe-LgbsSe[aria-label='다음 페이지로 이동']",
                "button[class*='enOdEe-wZVHId-gruSEe-LgbsSe'][aria-label='다음 페이지로 이동']",
                "button[class*='pYTkkf-Bz112c-LgbsSe'][aria-label='다음 페이지로 이동']",
                "button[jscontroller='PIVayb'][aria-label='다음 페이지로 이동']",
                "[jscontroller='PIVayb'][aria-label='다음 페이지로 이동']",
                "button[aria-label='다음 페이지로 이동']",
                "[aria-label='다음 페이지로 이동']",
                ".enOdEe-wZVHId-gruSEe-yXBf7b button[jsname='ViaHrd']",
                ".enOdEe-wZVHId-gruSEe-yXBf7b button[aria-label='다음 페이지로 이동']",
                ".enOdEe-wZVHId-gruSEe-yXBf7b button",
            ]
            
            await page.wait_for_timeout(1_000)  # 버튼 찾기 전 대기
            
            for selector in next_button_selectors:
                try:
                    next_btn = await page.query_selector(selector)
                    if next_btn:
                        # 버튼이 보이면 비활성화 상태와 관계없이 사용 (JavaScript로 강제 클릭 가능)
                        is_visible = await next_btn.is_visible()
                        if is_visible:
                            # 비활성화 상태 확인 (로그용)
                            is_enabled = await next_btn.is_enabled()
                            is_disabled = False
                            try:
                                disabled_attr = await next_btn.get_attribute("disabled")
                                aria_disabled = await next_btn.get_attribute("aria-disabled")
                                if disabled_attr is not None or aria_disabled == "true":
                                    is_disabled = True
                            except Exception:
                                pass
                            
                            if is_disabled or not is_enabled:
                                logger.debug("다음 페이지 버튼 발견 (비활성화 상태이지만 강제 클릭 시도): %s", selector)
                            else:
                                logger.debug("다음 페이지 버튼 발견: %s", selector)
                            break
                        else:
                            next_btn = None
                except Exception:
                    next_btn = None
                    continue
            
            # 버튼을 찾지 못한 경우, 페이지 하단으로 스크롤하여 재시도
            if not next_btn:
                logger.debug("버튼을 찾지 못함, 페이지 하단으로 스크롤하여 재시도...")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1_500)
                
                for selector in next_button_selectors[:5]:
                    try:
                        next_btn = await page.query_selector(selector)
                        if next_btn:
                            is_visible = await next_btn.is_visible()
                            if is_visible:
                                is_enabled = await next_btn.is_enabled()
                                is_disabled = False
                                try:
                                    disabled_attr = await next_btn.get_attribute("disabled")
                                    aria_disabled = await next_btn.get_attribute("aria-disabled")
                                    if disabled_attr is not None or aria_disabled == "true":
                                        is_disabled = True
                                except Exception:
                                    pass
                                
                                if is_disabled or not is_enabled:
                                    logger.debug("스크롤 후 버튼 발견 (비활성화 상태이지만 강제 클릭 시도): %s", selector)
                                else:
                                    logger.debug("스크롤 후 버튼 발견: %s", selector)
                            else:
                                next_btn = None
                            break
                    except Exception:
                        next_btn = None
                        continue
            
            if not next_btn:
                logger.debug("라운드 %s: 다음 페이지 버튼 없음 (수집: %s/%s개)", paged_round, len(trends), max_trends)
                break
            
            # 다음 페이지로 이동
            try:
                # 버튼이 뷰포트에 보이도록 스크롤
                await next_btn.scroll_into_view_if_needed()
                await page.wait_for_timeout(300)
                
                # 이전 페이지의 첫 번째 키워드 저장 (클릭 전)
                old_first_keyword = previous_first_keyword
                
                # JavaScript로 직접 클릭 (비활성화 상태 무시하고 강제 클릭)
                click_success = False
                try:
                    await next_btn.evaluate("""
                        el => {
                            // 비활성화 속성 제거 (일시적으로)
                            const wasDisabled = el.hasAttribute('disabled');
                            const wasAriaDisabled = el.getAttribute('aria-disabled');
                            if (wasDisabled) {
                                el.removeAttribute('disabled');
                            }
                            if (wasAriaDisabled === 'true') {
                                el.setAttribute('aria-disabled', 'false');
                            }
                            
                            // 1. onclick 핸들러 직접 호출
                            if (el.onclick) {
                                try {
                                    el.onclick();
                                } catch(e) {}
                            }
                            
                            // 2. click() 메서드 호출
                            try {
                                el.click();
                            } catch(e) {}
                            
                            // 3. MouseEvent로 클릭 이벤트 발생
                            const clickEvent = new MouseEvent('click', {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                detail: 1,
                                buttons: 1
                            });
                            el.dispatchEvent(clickEvent);
                            
                            // 4. mousedown, mouseup 이벤트도 발생
                            const mouseDownEvent = new MouseEvent('mousedown', {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                detail: 1,
                                buttons: 1
                            });
                            el.dispatchEvent(mouseDownEvent);
                            
                            const mouseUpEvent = new MouseEvent('mouseup', {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                detail: 1,
                                buttons: 1
                            });
                            el.dispatchEvent(mouseUpEvent);
                            
                            // 5. jsaction이 있으면 직접 실행
                            const jsaction = el.getAttribute('jsaction');
                            if (jsaction) {
                                const actions = jsaction.split(';');
                                for (let action of actions) {
                                    if (action.includes('click:')) {
                                        const handlerName = action.split(':')[1];
                                        if (window[handlerName]) {
                                            try {
                                                window[handlerName](new Event('click'));
                                            } catch(e) {}
                                        }
                                    }
                                }
                            }
                            
                            // 6. jsname 속성을 이용한 직접 호출
                            const jsname = el.getAttribute('jsname');
                            if (jsname === 'ViaHrd') {
                                try {
                                    const clickHandler = el.onclick || el.getAttribute('onclick');
                                    if (clickHandler) {
                                        eval(clickHandler.toString());
                                    }
                                } catch(e) {}
                            }
                        }
                    """)
                    click_success = True
                except Exception:
                    pass
                
                # Playwright 클릭 (JavaScript가 실패한 경우)
                if not click_success:
                    try:
                        await next_btn.click(timeout=5_000)
                        click_success = True
                    except Exception:
                        try:
                            await next_btn.click(force=True, timeout=5_000)
                            click_success = True
                        except Exception:
                            pass
                
                if not click_success:
                    # aria-label로 버튼 찾아서 JavaScript로 클릭
                    try:
                        await page.evaluate("""
                            () => {
                                const btn = document.querySelector("button[jsname='ViaHrd']");
                                if (btn) {
                                    btn.click();
                                    const clickEvent = new MouseEvent('click', {
                                        bubbles: true,
                                        cancelable: true,
                                        view: window
                                    });
                                    btn.dispatchEvent(clickEvent);
                                    return true;
                                }
                                return false;
                            }
                        """)
                        click_success = True
                    except Exception:
                        pass
                
                if not click_success:
                    raise Exception("모든 클릭 방법 실패")
                
                # 페이지 로드 대기
                await page.wait_for_timeout(2_000)  # 클릭 후 초기 대기
                
                # 페이지가 로드될 때까지 대기
                try:
                    await page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass
                
                # 스크롤하여 테이블이 완전히 로드되도록 함
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1_000)
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(1_000)
                
                # 테이블이 업데이트될 때까지 명시적으로 대기
                try:
                    # 테이블이 업데이트될 때까지 대기 (최대 15초)
                    table_updated = False
                    min_rows_expected = 20
                    last_row_count = 0
                    stable_count = 0
                    
                    for wait_attempt in range(15):
                        await page.wait_for_timeout(500)  # 0.5초마다 확인
                        
                        # 테이블 행 확인
                        new_rows = await page.query_selector_all("tbody tr")
                        current_row_count = len(new_rows)
                        
                        # 행 수가 안정적으로 유지되는지 확인
                        if current_row_count == last_row_count and current_row_count > 0:
                            stable_count += 1
                        else:
                            stable_count = 0
                        last_row_count = current_row_count
                        
                        # 행 수가 충분하고 안정적이며, 첫 번째 키워드가 변경되었는지 확인
                        if current_row_count >= min_rows_expected and stable_count >= 2:
                            # 첫 번째 행의 키워드 확인
                            first_row = new_rows[0]
                            keyword_elem = await first_row.query_selector(".mZ3RIc")
                            if keyword_elem:
                                new_first_keyword = (await keyword_elem.inner_text() or "").strip()
                                
                                # 이전 페이지의 첫 번째 키워드와 다르면 페이지가 변경된 것
                                if old_first_keyword is None or new_first_keyword != old_first_keyword:
                                    # 추가 검증: 마지막 행의 키워드도 확인
                                    last_row = new_rows[-1]
                                    last_keyword_elem = await last_row.query_selector(".mZ3RIc")
                                    if last_keyword_elem:
                                        last_keyword = (await last_keyword_elem.inner_text() or "").strip()
                                        # 첫 번째와 마지막 키워드가 모두 다르면 확실히 페이지가 변경된 것
                                        if last_keyword not in found:
                                            table_updated = True
                                            break

                        if wait_attempt == 14:
                            # 타임아웃이어도 첫 번째 키워드가 변경되었는지 확인
                            if current_row_count > 0:
                                first_row = new_rows[0]
                                keyword_elem = await first_row.query_selector(".mZ3RIc")
                                if keyword_elem:
                                    final_keyword = (await keyword_elem.inner_text() or "").strip()
                                    if final_keyword != old_first_keyword:
                                        table_updated = True
                except Exception:
                    pass
                
                # 추가 대기 및 스크롤 (동적 콘텐츠 로드)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1_500)  # 대기 시간
                await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(500)
            except Exception as e:
                logger.warning("다음 페이지 이동 실패: %s", e)
                break
        
        logger.info("방법 0 완료: 총 %s개 트렌드 수집", len(trends))
        
        # 방법 1, 2, 3 제거됨 (방법 0만 사용)

        await browser.close()

    trends = trends[:max_trends]
    # logger.info("Google Trends 수집 완료: %s개", len(trends))
    print("keyword searched. done.")
    print(trends)
    return {"total_trends": len(trends), "trends": trends}


async def get_trend_keywords(
    *,
    headless: bool = True,
    max_trends: int = 80,
    excluded_texts: Optional[Set[str]] = None,
    page_timeout_ms: int = 60_000,
) -> List[str]:
    """
    Google Trends에서 키워드 텍스트만 리스트로 반환한다.
    """
    result = await crawl_google_trends(
        headless=headless,
        max_trends=max_trends,
        excluded_texts=excluded_texts,
        page_timeout_ms=page_timeout_ms,
    )
    return [item["keyword"] for item in result.get("trends", []) if "keyword" in item]


async def get_keywords_and_send(
    *,
    headless: bool = True,
    max_trends: int = 80,
    excluded_texts: Optional[Set[str]] = None,
    page_timeout_ms: int = 60_000,
):
    result = await crawl_google_trends(
        headless=headless,
        max_trends=max_trends,
        excluded_texts=excluded_texts,
        page_timeout_ms=page_timeout_ms,
    )
    keywords = [
        item["keyword"] for item in result.get("trends", []) if "keyword" in item
    ]
    res_list = [
        {
            "categoryId": 1,
            "keyword": keyword,
            "searchVolume": 0,
            "snsType": "google",
        }
        for keyword in keywords
    ]
    print(res_list)
    requests.post(
        url=JAVA_SERVER_ADDRESS + "/api/trend",
        headers={"Content-Type": "application/json"},
        json=res_list,
        timeout=15000,
    )
    return res_list


__all__ = [
    "crawl_google_trends",
    "TREND_URL",
    "EXCLUDED_TEXTS",
    "get_trend_keywords",
    "get_keywords_and_send",
]
