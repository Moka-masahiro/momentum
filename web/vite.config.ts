import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // GitHub Pages では https://<ユーザー名>.github.io/<リポジトリ名>/ の下に置かれるので、
  // 読み込むファイルはすべて相対パスで参照する
  base: "./",
  build: {
    // 構文は古めのブラウザでも動く形に変換する（実行時の機能は data.ts で確認する）
    target: ["es2018", "chrome80", "safari14"],
  },
});
