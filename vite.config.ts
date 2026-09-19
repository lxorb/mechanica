import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/*.png', 'icons/*.svg'],
      manifest: {
        name: 'Trust the manual',
        short_name: 'Manual',
        description: 'Official motorcycle service manual, right page.',
        theme_color: '#000000',
        background_color: '#000000',
        display: 'standalone',
        orientation: 'portrait',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
      workbox: {
        maximumFileSizeToCacheInBytes: 30 * 1024 * 1024,
        globPatterns: ['**/*.{js,css,html,png,svg,json,woff2}'],
        runtimeCaching: [
          { urlPattern: /\/manuals\/.*\.pdf$/, handler: 'CacheFirst', options: { cacheName: 'manuals' } },
        ],
      },
    }),
  ],
})
