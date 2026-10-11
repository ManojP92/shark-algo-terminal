/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        shark: {
          bg: '#0b0e14',
          card: '#121721',
          border: '#1e2638',
          accent: '#00e5ff',
          green: '#00e676',
          red: '#ff1744',
          gold: '#ffd600',
        }
      }
    },
  },
  plugins: [],
}
