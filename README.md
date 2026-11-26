# KOSDAQ Filings Tracker

코스닥·중소형주 공시를 매일 자동으로 모아 영어로 요약하고, 정적 웹사이트로 배포하는 프로젝트입니다.

```
collect.py   → DART에서 6개 유형 공시 수집         (data/raw/)
summarize.py → AI 영문 요약 + 숫자 대조 검사        (통과: data/filings/, 불일치: data/held/)
build.py     → 정적 사이트 생성                     (site/)
GitHub Actions가 평일 23시 17분(한국시간)에 위 3단계를 실행하고 GitHub Pages에 배포합니다.
```

## 1. 내 컴퓨터에서 데모로 보기 (키 없이)

```bash
pip install -r requirements.txt
DEMO=1 python collect.py && DEMO=1 python summarize.py && DEMO=1 python build.py
cd site && python -m http.server 8000     # 브라우저에서 http://localhost:8000
```

데모는 가상의 "Sample ___" 회사 7곳을 씁니다. 그중 1건(합병비율 오기)은 숫자 검사에서 일부러 걸리도록 만들어 `data/held/`로 빠집니다.

데모를 본 뒤 실제 운영 전에는 데모 데이터를 지우세요.

```bash
rm -rf data/filings data/held data/raw data/companies.json site
```

## 2. 준비물

| 준비물 | 어디서 | 비용 |
| --- | --- | --- |
| GitHub 계정 + 공개 저장소 | github.com | 무료 (호스팅도 GitHub Pages로 무료) |
| DART API 키 | opendart.fss.or.kr → 인증키 신청 | 무료 |
| AI 요약 API 키 | console.anthropic.com (Claude API) | 사용량만큼 |
| 도메인 (애드센스 신청 전까지) | 가비아, Cloudflare Registrar 등 | 연 1~2만 원 |

## 3. 설치 순서

1. **코드 올리기** — 이 폴더를 공개 저장소 `kosdaq-tracker`의 `main` 브랜치에 올립니다.
2. **Pages 켜기** — 저장소 Settings → Pages → Build and deployment → Source를 **GitHub Actions**로 바꿉니다.
   → 이후 코드가 바뀔 때마다 사이트가 다시 배포됩니다. 주소: `https://<아이디>.github.io/kosdaq-tracker/`
3. **키 등록** — Settings → Secrets and variables → Actions → **Secrets** 탭에서 New repository secret:
   | 이름 | 값 |
   | --- | --- |
   | `DART_API_KEY` | DART 인증키 |
   | `ANTHROPIC_API_KEY` | Claude API 키 |

   키가 없으면 수집·요약 단계는 건너뛰고 사이트(가이드·필수 페이지)만 배포됩니다.
4. **선택 설정** — 같은 화면의 **Variables** 탭:
   | 이름 | 예시 |
   | --- | --- |
   | `SITE_URL` | 도메인 연결 후 `https://www.내도메인.com` (비우면 github.io 주소) |
   | `SITE_NAME` | `KOSDAQ Filings Tracker` |
   | `CONTACT_EMAIL` | 사이트용 문의 이메일 (개인 메일과 분리 권장) |
   | `ANTHROPIC_MODEL` | 비워두면 `claude-haiku-5-5` |
5. **첫 실행** — Actions 탭 → "Daily filings" → Run workflow → days에 `5` 입력 (최근 5일치로 시작).
6. **도메인 연결** — Settings → Pages → Custom domain에 도메인 입력, 도메인 업체 DNS에 GitHub가 안내하는 레코드 추가, 그다음 `SITE_URL` 변수를 새 도메인으로 바꿉니다.
7. **Google Search Console** — 사이트 등록 후 `<사이트 주소>/sitemap.xml` 제출.

이후로는 평일 밤 11시 17분마다 자동으로 돌아갑니다. 매번 최근 4일치를 다시 확인해서, 늦게 올라온 공시나 건너뛴 날도 채워집니다.

## 4. 애드센스 붙이기

1. 가이드 글이 15편 이상 쌓이면 애드센스에 사이트를 신청합니다.
2. 애드센스의 게시자 ID(`ca-pub-…`)를 GitHub Variables에 `ADSENSE_PUB_ID`로 넣습니다.
   → 모든 페이지에 애드센스 코드가, 사이트 루트에 `ads.txt`가 자동으로 생깁니다.
3. 승인 후 원하면 광고 단위를 만들어 슬롯 번호를 `ADSENSE_SLOT_INARTICLE`(공시 본문 중간), `ADSENSE_SLOT_LIST`(목록 중간)에 넣습니다. 비워두면 자동 광고만 씁니다.

## 5. 주 1회 할 일

- `data/held/` 확인: 숫자 검사에서 걸린 요약입니다. 각 파일의 `held_reasons`를 보고
  - 요약이 틀렸으면 `summary`를 고쳐서 파일을 `data/filings/`로 옮기고 (`text` 항목은 지워도 됨)
  - 검사가 지나쳤으면(예: 단위 표기 차이) 그대로 옮기면 됩니다.
- `guides/`에 가이드 글 추가 (아래 형식). `draft: true`면 게시되지 않습니다.

```markdown
---
title: 글 제목
description: 검색 결과에 보일 한두 문장
updated: November 2026
events: buyback        # 연결할 공시 유형 키 (buyback, dividend, capital, control, contract, mna)
---
본문 (마크다운)
```

## 6. 설정 바꾸기

- 다루는 공시 유형: `config.py`의 `EVENT_TYPES`
- 제외할 대형주: `data/exclude.txt`에 종목코드 한 줄씩 (영문 공시 의무가 있는 대형 코스피 종목)
- 실행 시각: `.github/workflows/daily.yml`의 `cron` (UTC 기준, `17 14` = 한국 23시 17분)

## 주의

- 요약에는 매수·매도 권유나 목표가가 들어가지 않도록 프롬프트와 검사로 막혀 있습니다. 유료 추천 서비스로 확장하려면 먼저 관련 규제를 확인하세요.
- OpenDART 이용약관의 출처 표기 조건을 확인하세요. 모든 페이지 하단에 "Source: DART, Financial Supervisory Service"가 표시됩니다.
- 함께 들어 있는 가이드 3편과 About·Privacy·Disclaimer 페이지는 초안입니다. 게시 전에 한 번 읽고 본인 관점을 더해 주세요.
