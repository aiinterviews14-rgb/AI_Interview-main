"use client";

import React, { createContext, useState, useContext, useEffect } from 'react';

type Theme = 'light' | 'dark';

type ThemeContextType = {
    theme: Theme;
    toggleTheme: () => void;
    setTheme: (t: Theme) => void;
};

const ThemeContext = createContext<ThemeContextType>({
    theme: 'light',
    toggleTheme: () => { },
    setTheme: () => { },
});

export const ThemeProvider = ({ children }: { children: React.ReactNode }) => {
    const [theme, setThemeState] = useState<Theme>(() => {
        if (typeof window === 'undefined') return 'light';
        const stored = localStorage.getItem('app_theme') as Theme | null;
        if (stored === 'dark' || stored === 'light') return stored;
        if (window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
        return 'light';
    });

    const applyTheme = (t: Theme) => {
        const root = document.documentElement; // <html>
        root.classList.remove('light', 'dark');
        root.classList.add(t);
        root.setAttribute('data-theme', t);
        document.body.classList.remove('light', 'dark');
        document.body.classList.add(t);
        localStorage.setItem('app_theme', t);
    };

    // Keep DOM classes synchronized with current theme
    useEffect(() => {
        applyTheme(theme);
    }, [theme]);

    const setTheme = (t: Theme) => {
        setThemeState(t);
    };

    const toggleTheme = () => {
        const next = theme === 'light' ? 'dark' : 'light';
        setTheme(next);
    };

    return (
        <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
            {children}
        </ThemeContext.Provider>
    );
};

export const useTheme = () => useContext(ThemeContext);
