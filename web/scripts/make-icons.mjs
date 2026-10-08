// 앱 아이콘 생성: 아래 SVG 원본(D2 시안) 하나로 탭·홈 화면·설치용 아이콘을 모두 만든다.
// 아이콘을 바꿀 때는 ART 만 고치고 `node scripts/make-icons.mjs` (web/ 에서) 로 다시 만든다.
// PNG 변환은 Next.js 가 함께 설치하는 sharp 를 쓴다.
import { mkdir, writeFile } from "node:fs/promises";
import sharp from "sharp";

const BG = "#f7f6f2";
// 왼쪽에서 흘러온 기사 세 줄이 i 의 점(이슈)으로 모이고, 그 아래 i 의 기둥 (viewBox 100×100)
const ART = `
  <g fill="none" stroke="#2a78d6" stroke-width="6" stroke-linecap="round">
    <path d="M18 20 C34 20 40 33 54 33" opacity=".45"/>
    <path d="M18 33 L54 33"/>
    <path d="M18 46 C34 46 40 33 54 33" opacity=".45"/>
  </g>
  <circle cx="64" cy="33" r="10" fill="#2a78d6"/>
  <rect x="57" y="50" width="14" height="32" rx="7" fill="#0b0b0b"/>`;

const svg = ({ radius = 0, scale = 1 } = {}) => {
  const off = (100 - 100 * scale) / 2;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect width="100" height="100" rx="${radius}" fill="${BG}"/>
  <g transform="translate(${off} ${off}) scale(${scale})">${ART}</g>
</svg>
`;
};

const png = (src, size, out) => sharp(Buffer.from(src), { density: 72 * (size / 100) * 2 })
  .resize(size, size).png().toFile(out);

await mkdir("public/icons", { recursive: true });
// 브라우저 탭: 둥근 모서리 SVG (모든 크기에서 선명)
await writeFile("app/icon.svg", svg({ radius: 22 }));
// iPhone 홈 화면: 꽉 찬 정사각형 (모서리는 iOS 가 둥글게 자른다)
await png(svg(), 180, "app/apple-icon.png");
// Android·Chrome 설치용: 그대로 쓰는 둥근 아이콘 + 원·물방울로 잘려도 안전하도록 그림을 80% 로 줄인 maskable
await png(svg({ radius: 22 }), 192, "public/icons/icon-192.png");
await png(svg({ radius: 22 }), 512, "public/icons/icon-512.png");
await png(svg({ scale: 0.8 }), 512, "public/icons/icon-maskable-512.png");
console.log("아이콘 생성 완료: app/icon.svg, app/apple-icon.png, public/icons/*.png");
