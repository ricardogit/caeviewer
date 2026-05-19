import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'

try {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
} catch (e) {
  const el = document.getElementById('root')
  if (el) el.innerHTML = '<pre style="background:#1a0000;color:#ff6666;padding:24px;font:13px/1.6 monospace;position:fixed;inset:0;overflow:auto;z-index:9999;white-space:pre-wrap">REACT MOUNT ERROR\n' + (e.stack || e) + '</pre>'
}
