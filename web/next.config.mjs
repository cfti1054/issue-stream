/** @type {import('next').NextConfig} */
const nextConfig = {
  // 화면은 서버에서 API(FastAPI)를 호출해 그린다. 브라우저는 API 주소를 몰라도 된다.
  reactStrictMode: true,
};
export default nextConfig;
