// 수집 상태 안내: 첫 실행 중이거나 수집 작업이 실패하고 있을 때만 보인다.
import type { CollectionStatus } from "@/lib/api";
import { timeKST } from "@/lib/format";

export default function StatusBanner({ s, empty }: { s: CollectionStatus; empty: boolean }) {
  return (
    <>
      {s.first_run && s.scheduler && (
        <div className="banner info" role="status">
          <b>첫 데이터를 모으는 중입니다.</b> 시세·뉴스를 처음 받아오는 데 1~2분 걸립니다. 화면은 자동으로 새로고침됩니다.
        </div>
      )}
      {empty && !s.scheduler && s.first_run && (
        <div className="banner warn" role="status">
          <b>수집기가 꺼져 있습니다.</b> 프로젝트 폴더에서 <code>issue-stream serve</code> 로 실행하면 데이터가 채워집니다.
        </div>
      )}
      {s.problems.length > 0 && <Problems s={s} />}
    </>
  );
}

function Problems({ s }: { s: CollectionStatus }) {
  return (
    <div className="banner warn" role="status">
      <b>일부 데이터를 가져오지 못하고 있습니다.</b>{" "}
      <code>issue-stream doctor</code> 로 어떤 소스가 막혔는지 확인하세요.
      <ul>
        {s.problems.map((p) => (
          <li key={p.job}><b>{p.label}</b> <span className="muted">{timeKST(p.at)}</span> — {p.message}</li>
        ))}
      </ul>
    </div>
  );
}
