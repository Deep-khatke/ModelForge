/**
 * Firebase Web Client SDK initialization and Authentication helpers.
 *
 * Configured using public client variables in .env (VITE_FIREBASE_*).
 * Falls back gracefully when Firebase client credentials are not configured.
 */
import { initializeApp, getApps, getApp } from "firebase/app";
import {
  getAuth,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  updateProfile,
  signOut,
  onAuthStateChanged,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY || "",
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || "",
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || "",
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || "",
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || "",
  appId: import.meta.env.VITE_FIREBASE_APP_ID || "",
};

export const isFirebaseConfigured = Boolean(
  firebaseConfig.apiKey && firebaseConfig.projectId
);

let app = null;
let auth = null;

if (isFirebaseConfigured) {
  try {
    app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApp();
    auth = getAuth(app);
  } catch (err) {
    console.warn("Failed to initialize Firebase client SDK:", err);
  }
}

export function getFirebaseAuth() {
  return auth;
}

export async function loginWithFirebase(email, password) {
  if (!auth) {
    throw new Error("Firebase Authentication is not configured on the frontend.");
  }
  const credential = await signInWithEmailAndPassword(auth, email, password);
  const token = await credential.user.getIdToken();
  return { user: credential.user, token };
}

export async function registerWithFirebase(email, password, displayName) {
  if (!auth) {
    throw new Error("Firebase Authentication is not configured on the frontend.");
  }
  const credential = await createUserWithEmailAndPassword(auth, email, password);
  if (displayName && credential.user) {
    await updateProfile(credential.user, { displayName });
  }
  const token = await credential.user.getIdToken();
  return { user: credential.user, token };
}

export async function logoutFromFirebase() {
  if (!auth) return;
  await signOut(auth);
}

export async function getFirebaseIdToken() {
  if (!auth || !auth.currentUser) return null;
  return auth.currentUser.getIdToken();
}

export function onFirebaseAuthStateChanged(callback) {
  if (!auth) {
    callback(null);
    return () => {};
  }
  return onAuthStateChanged(auth, callback);
}
