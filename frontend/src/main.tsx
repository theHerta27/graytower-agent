import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import CampPage from './CampPage';
import './styles.css';

createRoot(document.getElementById('root')!).render(<StrictMode>{location.pathname === '/camp' ? <CampPage /> : <App />}</StrictMode>);
