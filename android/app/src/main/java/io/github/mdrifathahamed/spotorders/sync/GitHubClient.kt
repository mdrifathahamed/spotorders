package io.github.mdrifathahamed.spotorders.sync

import android.util.Base64
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Minimal GitHub REST client: read a file, write a file, fire a repository_dispatch. */
class GitHubClient(private val token: String, private val owner: String) {

    data class RemoteFile(val sha: String?, val text: String)

    private fun open(path: String, method: String): HttpURLConnection =
        (URL("https://api.github.com$path").openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 15_000
            readTimeout = 30_000
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
            setRequestProperty("User-Agent", "Spotorders-Android")
        }

    private fun HttpURLConnection.errorText(): String =
        "HTTP $responseCode " + (errorStream?.bufferedReader()?.use { it.readText() }?.take(200) ?: "")

    fun getFile(repo: String, path: String): RemoteFile {
        val c = open("/repos/$owner/$repo/contents/$path", "GET")
        try {
            return when (c.responseCode) {
                200 -> {
                    val js = JSONObject(c.inputStream.bufferedReader().use { it.readText() })
                    val b64 = js.optString("content", "").replace("\n", "")
                    RemoteFile(js.getString("sha"), String(Base64.decode(b64, Base64.DEFAULT), Charsets.UTF_8))
                }
                404 -> RemoteFile(null, "")
                else -> throw IOException("GET $path: ${c.errorText()}")
            }
        } finally {
            c.disconnect()
        }
    }

    fun putFile(repo: String, path: String, text: String, sha: String?, message: String) {
        val c = open("/repos/$owner/$repo/contents/$path", "PUT")
        try {
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            val body = JSONObject()
                .put("message", message)
                .put("content", Base64.encodeToString(text.toByteArray(Charsets.UTF_8), Base64.NO_WRAP))
            if (sha != null) body.put("sha", sha)
            c.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            if (c.responseCode !in 200..201) throw IOException("PUT $path: ${c.errorText()}")
        } finally {
            c.disconnect()
        }
    }

    /** Appends lines to a CSV file, creating it with `header` if it does not exist yet. */
    fun appendCsv(repo: String, path: String, header: String, lines: List<String>, message: String) {
        if (lines.isEmpty()) return
        val f = getFile(repo, path)
        val base = if (f.text.isBlank()) "$header\n" else f.text.trimEnd('\n') + "\n"
        putFile(repo, path, base + lines.joinToString("\n") + "\n", f.sha, message)
    }

    fun dispatch(repo: String, eventType: String) {
        val c = open("/repos/$owner/$repo/dispatches", "POST")
        try {
            c.doOutput = true
            c.setRequestProperty("Content-Type", "application/json")
            c.outputStream.use { it.write(JSONObject().put("event_type", eventType).toString().toByteArray()) }
            if (c.responseCode != 204) throw IOException("dispatch: ${c.errorText()}")
        } finally {
            c.disconnect()
        }
    }
}
