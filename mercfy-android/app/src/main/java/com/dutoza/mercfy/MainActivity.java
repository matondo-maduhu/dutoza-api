package com.dutoza.mercfy;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Bundle;
import android.provider.MediaStore;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.FileProvider;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

import java.io.File;

public class MainActivity extends AppCompatActivity {
    private static final String HOME = "https://mercyfy.dutoza.com/feed";
    private static final String HOST = "mercyfy.dutoza.com";
    private static final String ERROR_PAGE = "file:///android_asset/offline.html";
    private static final int FILE_REQ = 1001;
    private static final int CAPTURE_REQ = 1002;

    private WebView web;
    private SwipeRefreshLayout refresh;
    private ValueCallback<Uri[]> filePathCallback;
    private Uri captureUri; // faili ya picha/video kutoka kamera

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        web = new WebView(this);
        refresh = new SwipeRefreshLayout(this);
        refresh.addView(web, new ViewGroup.LayoutParams(-1, -1));
        setContentView(refresh);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false); // muziki na video
        s.setAllowFileAccess(false);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);

        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(web, false);

        refresh.setOnRefreshListener(() -> {
            // Ukiwa kwenye ukurasa wa hitilafu, vuta-kuonyesha-upya inajaribu ukurasa uliofeli
            if (onErrorPage()) web.loadUrl(retryTarget());
            else web.reload();
        });

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if (HOST.equalsIgnoreCase(u.getHost())) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) {}
                return true; // viungo vya nje vinafunguka kwenye browser
            }
            @Override public void onPageFinished(WebView v, String url) { refresh.setRefreshing(false); cm.flush(); }
            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                // Hakuna jibu kabisa: ama huna mtandao, ama seva haifikiki
                if (r.isForMainFrame()) {
                    refresh.setRefreshing(false);
                    showErrorPage(isOnline() ? "server" : "offline", r.getUrl().toString());
                }
            }
            @Override
            public void onReceivedHttpError(WebView v, WebResourceRequest r, WebResourceResponse resp) {
                // Seva imejibu na hitilafu (mf. 502 Bad Gateway ya Render wakati seva inaamka)
                if (!r.isForMainFrame()) return;
                int code = resp.getStatusCode();
                if (code == 502 || code == 503 || code == 504) {
                    refresh.setRefreshing(false);
                    showErrorPage("server", r.getUrl().toString());
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                filePathCallback = cb;
                captureUri = null;

                // Kitufe cha "Kamera" / "Video" kwenye feed (input yenye capture)
                if (p.isCaptureEnabled()) {
                    String kind = captureKind(p.getAcceptTypes());
                    if (kind != null && launchCapture(kind)) return true;
                }

                // "Galeri" (au capture ikishindwa): chagua faili
                try { startActivityForResult(p.createIntent(), FILE_REQ); }
                catch (Exception e) { filePathCallback = null; return false; }
                return true;
            }
        });

        if (savedInstanceState != null) web.restoreState(savedInstanceState);
        else web.loadUrl(HOME);
    }

    /** "image" au "video" kulingana na accept="..." ya input, vinginevyo null. */
    private static String captureKind(String[] accept) {
        if (accept == null) return null;
        for (String a : accept) {
            if (a == null) continue;
            if (a.startsWith("video")) return "video";
            if (a.startsWith("image")) return "image";
        }
        return null;
    }

    private boolean launchCapture(String kind) {
        try {
            File dir = new File(getCacheDir(), "captures");
            if (!dir.exists() && !dir.mkdirs()) return false;
            boolean video = "video".equals(kind);
            File out = File.createTempFile(video ? "mercfy_vid_" : "mercfy_img_", video ? ".mp4" : ".jpg", dir);
            captureUri = FileProvider.getUriForFile(this, getPackageName() + ".fileprovider", out);

            Intent i = new Intent(video ? MediaStore.ACTION_VIDEO_CAPTURE : MediaStore.ACTION_IMAGE_CAPTURE);
            i.putExtra(MediaStore.EXTRA_OUTPUT, captureUri);
            i.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivityForResult(i, CAPTURE_REQ);
            return true;
        } catch (Exception e) {
            captureUri = null;
            return false;
        }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if ((req == FILE_REQ || req == CAPTURE_REQ) && filePathCallback != null) {
            Uri[] result = null;
            if (res == Activity.RESULT_OK) {
                if (req == CAPTURE_REQ) {
                    if (captureUri != null) result = new Uri[]{captureUri};
                    else if (data != null && data.getData() != null) result = new Uri[]{data.getData()};
                } else if (data != null) {
                    result = WebChromeClient.FileChooserParams.parseResult(res, data);
                }
            }
            filePathCallback.onReceiveValue(result);
            filePathCallback = null;
            captureUri = null;
        } else {
            super.onActivityResult(req, res, data);
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) { super.onSaveInstanceState(out); web.saveState(out); }

    /** Fungua ukurasa wetu safi wa hitilafu (assets/offline.html) badala ya ukurasa wa Render. */
    private void showErrorPage(String kind, String failedUrl) {
        String retry = HOME;
        try {
            Uri f = Uri.parse(failedUrl);
            if ("https".equalsIgnoreCase(f.getScheme()) && HOST.equalsIgnoreCase(f.getHost())) retry = failedUrl;
        } catch (Exception ignored) {}
        web.loadUrl(ERROR_PAGE + "?c=" + kind + "&u=" + Uri.encode(retry));
    }

    private boolean onErrorPage() {
        String u = web.getUrl();
        return u != null && u.startsWith("file:///android_asset/");
    }

    /** Anwani iliyofeli (kutoka ukurasa wa hitilafu), au HOME kama haipo. */
    private String retryTarget() {
        try {
            String u = Uri.parse(web.getUrl()).getQueryParameter("u");
            if (u != null) {
                Uri p = Uri.parse(u);
                if ("https".equalsIgnoreCase(p.getScheme()) && HOST.equalsIgnoreCase(p.getHost())) return u;
            }
        } catch (Exception ignored) {}
        return HOME;
    }

    private boolean isOnline() {
        try {
            ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
            if (cm == null) return true;
            Network n = cm.getActiveNetwork();
            if (n == null) return false;
            NetworkCapabilities c = cm.getNetworkCapabilities(n);
            return c != null && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
        } catch (Exception e) {
            return true;
        }
    }

    @Override
    public void onBackPressed() {
        // Kwenye ukurasa wa hitilafu, "nyuma" inatoka kwenye app (isirudi kwenye ukurasa uliofeli)
        if (onErrorPage()) { finish(); return; }
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }
}
