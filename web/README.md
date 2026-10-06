# web — 대시보드 화면 (Next.js)

기획서 6장의 두 화면을 구현했다.

| 화면 | 주소 | 구성 (위 → 아래: 결론 → 근거) |
|---|---|---|
| 마켓 대시보드 | `http://localhost:3000/` | 지수 스트립 → AI 요약 → 관심종목·가격 차트 → 주요 뉴스·업종 히트맵 |
| 이슈 브리핑 | `http://localhost:3000/issues` | 기간·감성·종목 필터 → 이슈 카드 (요약 → 출처 → 불릿 → 종목 태그 → 보도량 추이 → 근거 기사 펼치기) |

## 실행

Windows 에서는 프로젝트 루트의 **`start-dashboard.cmd`** 를 더블클릭하면 아래가 모두 실행된다.

```bash
# 1) 백엔드: API + 수집기 (프로젝트 루트에서). DB(SQLite)는 자동 생성
issue-stream serve             # http://127.0.0.1:8000
# (선택) 수집이 막혀도 화면을 보고 싶으면: issue-stream seed-demo

# 2) 웹 (이 폴더에서, Node.js 20 이상)
npm install                    # 최초 1회
npm run dev                    # http://localhost:3000
```

첫 실행 중이거나 수집이 실패하고 있으면 대시보드 상단에 안내 배너가 뜬다.

운영용으로 띄울 때는 `npm run build && npm start` 를 쓴다.

## 설정 (`.env.local`, 선택)

`env.local.example` 을 `.env.local` 로 복사해서 쓴다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `API_BASE` | `http://127.0.0.1:8000` | FastAPI 주소. 화면은 서버에서 API를 호출하므로 브라우저에는 노출되지 않는다 |
| `NEXT_PUBLIC_REFRESH_SECONDS` | `60` | 자동 새로고침 주기(초). 탭이 보일 때만 갱신. `0` 이면 끔 |

## 설계 원칙

- **프론트는 계산하지 않는다.** 중요도·감성 집계·보도량 추이·AI 요약은 모두 API(`/dashboard`, `/issues`)가 완성된 값으로 내려준다.
- **색은 두 쌍만.** 등락은 상승 빨강 / 하락 파랑(한국 관례), 감성은 긍정 초록 / 중립 회색 / 부정 빨강.
  색만으로 뜻을 전달하지 않도록 등락에는 ▲▼, 감성에는 "긍정/부정" 글자와 개수를 항상 함께 쓴다.
- **숫자 크기 3단계.** 22px(핵심 값) / 13px(표·등락) / 11px(보조 정보). `app/globals.css` 의 `--fs-num-*`.
- **종목 태그로 두 화면을 연결.** 이슈 카드의 종목 태그 → 대시보드의 해당 종목 차트, 관심종목의 대표 이슈 → 이슈 브리핑의 해당 카드.
- **라이트/다크 모드**는 OS 설정을 따른다. 모바일(360px~)에서도 가로 스크롤 없이 한 열로 쌓인다.
- 차트는 외부 라이브러리 없이 SVG로 직접 그린다 (`components/charts.tsx`, `components/PriceChart.tsx`).

## 폴더

```
web/
├── app/
│   ├── layout.tsx        # 상단 내비게이션, 자동 새로고침
│   ├── page.tsx          # 마켓 대시보드
│   ├── issues/page.tsx   # 이슈 브리핑
│   └── globals.css       # 디자인 토큰 (라이트/다크), 레이아웃
├── components/
│   ├── charts.tsx        # 스파크라인, 뉴스 심리 막대, 업종 히트맵, 보도량 막대
│   ├── PriceChart.tsx    # 가격 차트 (기간 선택, 호버 십자선·툴팁)
│   ├── IssueCard.tsx     # 이슈 카드
│   ├── chrome.tsx        # 내비게이션·새로고침·종목 필터 (클라이언트)
│   └── ErrorBox.tsx      # API 연결 실패 안내
└── lib/
    ├── api.ts            # API 타입·호출
    └── format.ts         # 숫자·시각 표시 형식
```
