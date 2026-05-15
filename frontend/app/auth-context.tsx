"use client";

import React, { createContext, useState, useContext, useEffect } from 'react';
import { profilePhotoSrc } from '@/lib/profilePhotoSrc';

type User = {
    id: number;
    name: string;
    email: string;
    phone: string;
    college_name?: string;
    branch?: string;
    domain?: string;
    register_no?: string;
    photo?: string;
    resume_path?: string;
    role: string;
    year?: string;
    is_premium?: number;
    plan_id?: number;
    interviews_remaining?: number;
    resume_score?: number;
    resume_feedback?: string;
};

/** Ensure stored profile photo works as an <img src> (raw base64 → data URL). */
function withDisplayablePhoto<T extends { photo?: string }>(u: T): T {
  if (!u?.photo?.trim()) return u;
  const fixed = profilePhotoSrc(u.photo);
  if (!fixed || fixed === u.photo) return u;
  return { ...u, photo: fixed };
}

type AuthContextType = {
    user: User | null;
    loading: boolean;
    login: (userData: User) => void;
    logout: () => void;
    updateUser: (userData: User) => void;
};

const AuthContext = createContext<AuthContextType>({
    user: null,
    loading: true,
    login: () => { },
    logout: () => { },
    updateUser: () => { },
});

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
    const [user, setUser] = useState<User | null>(null);
    const [loading] = useState(false);

    useEffect(() => {
        if (typeof window !== 'undefined') {
            const stored = localStorage.getItem('user_session');
            if (stored) {
                try {
                    setUser(withDisplayablePhoto(JSON.parse(stored)));
                } catch {
                    setUser(null);
                }
            }
        }
        
        // ── Cross-tab logout sync ─────────────────────────────────────────
        const handleStorageChange = (event: StorageEvent) => {
            if (event.key === 'user_session' || event.key === 'admin_session') {
                if (event.newValue === null) {
                    // Session was removed in another tab → log out this tab too
                    setUser(null);
                    // Force a reload if we are on a protected page to ensure state is reset
                    if (window.location.pathname !== '/' && !window.location.pathname.includes('login')) {
                        window.location.href = '/';
                    }
                } else if (event.key === 'user_session') {
                    // Session was updated (e.g. profile save) → sync user data
                    try {
                        setUser(withDisplayablePhoto(JSON.parse(event.newValue)));
                    } catch (e) {
                        console.error("Failed to sync user session across tabs", e);
                    }
                }
            }
        };

        window.addEventListener('storage', handleStorageChange);

        return () => {
            window.removeEventListener('storage', handleStorageChange);
        };
    }, []);

    const login = (userData: User) => {
        const u = withDisplayablePhoto(userData);
        setUser(u);
        localStorage.setItem('user_session', JSON.stringify(u));
    };

    const logout = () => {
        // 1. Clear everything locally FIRST (synchronous) so the user is immediately logged out
        setUser(null);
        localStorage.removeItem('user_session');
        localStorage.removeItem('admin_session');
        localStorage.removeItem('resume_uploaded');

        // 2. Fire backend logout in background (don't await — don't block redirect)
        const baseUrl = typeof window !== 'undefined' ? (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000') : (process.env.INTERNAL_BACKEND_URL || 'http://backend:5000');
        fetch(`${baseUrl}/api/auth/logout`, { method: 'POST' }).catch(() => {});

        // 3. Redirect to home
        window.location.href = '/';
    };

    const updateUser = (userData: User) => {
        const u = withDisplayablePhoto(userData);
        setUser(u);
        try {
            localStorage.setItem('user_session', JSON.stringify(u));
        } catch (e) {
            console.error("LocalStorage Update Failed (Quota likely exceeded):", e);
            // Fallback: save without photo if it's the culprit
            if (u.photo) {
                const { photo, ...rest } = u;
                localStorage.setItem('user_session', JSON.stringify(rest));
            }
        }
    };

    return (
        <AuthContext.Provider value={{ user, loading, login, logout, updateUser }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);

