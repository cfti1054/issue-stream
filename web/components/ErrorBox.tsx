export default function ErrorBox({ message, apiBase }: { message: string; apiBase: string }) {
  return (
    <div className="card error-box" role="alert">
      <h2>데이터를 불러오지 못했습니다</h2>
      <p className="ink2">{message}</p>
      <p className="muted">API 서버가 켜져 있는지 확인하세요. 프로젝트 폴더에서:</p>
      <pre>{`issue-stream serve          # API + 수집 (${apiBase})
issue-stream doctor         # 무료 데이터 소스 점검`}</pre>
    </div>
  );
}
