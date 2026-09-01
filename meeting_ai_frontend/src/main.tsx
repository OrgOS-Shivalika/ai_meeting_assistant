import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { initBackground } from './shared/background'
import { initTheme } from './shared/theme'

// Before render, not in an effect: applying it after mount paints the default
// first and then swaps, which is a visible flash on every page load.
// Theme FIRST: `applyBackground` checks for the dark class to decide whether
// to apply a (light) colour preset, so the class has to exist by then.
initTheme()
initBackground()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
