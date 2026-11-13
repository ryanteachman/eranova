import React from 'react'
import ReactDOM from 'react-dom/client'
import 'leaflet/dist/leaflet.css'
import './styles.css'
import App from './App.jsx'
import AppV1 from './v1/AppV1.jsx'
import AppV2 from './v2/AppV2.jsx'

// v3 (simple) is the default. Earlier layouts stay reachable as archives: /?v1 and /?v2.
const params = new URLSearchParams(window.location.search)
const Root = params.has('v1') ? AppV1 : params.has('v2') ? AppV2 : App

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
