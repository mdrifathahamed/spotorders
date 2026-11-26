package io.github.mdrifathahamed.spotorders.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** GitHub sync settings. The token is stored encrypted with the Android Keystore. */
class AppSettings(ctx: Context) {
    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        ctx,
        "spotorders_settings",
        MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var owner: String
        get() = prefs.getString("owner", "mdrifathahamed") ?: ""
        set(v) = prefs.edit().putString("owner", v.trim()).apply()

    /** Private repo that receives the raw log (times + GPS). */
    var dataRepo: String
        get() = prefs.getString("data_repo", "spotorders-data") ?: ""
        set(v) = prefs.edit().putString("data_repo", v.trim()).apply()

    /** Public repo whose workflow rebuilds the dataset after each upload. */
    var publicRepo: String
        get() = prefs.getString("public_repo", "spotorders") ?: ""
        set(v) = prefs.edit().putString("public_repo", v.trim()).apply()

    var token: String
        get() = prefs.getString("token", "") ?: ""
        set(v) = prefs.edit().putString("token", v.trim()).apply()

    var lastSyncMillis: Long
        get() = prefs.getLong("last_sync", 0L)
        set(v) = prefs.edit().putLong("last_sync", v).apply()

    var lastError: String
        get() = prefs.getString("last_error", "") ?: ""
        set(v) = prefs.edit().putString("last_error", v).apply()

    /**
     * Off (default): no GPS between O and D, and the D tap is rounded to ~100 m.
     * On: the whole route is kept, delivery trips and exact drop-off points included
     * (stored only in the private data repo).
     */
    var recordDeliveryTrips: Boolean
        get() = prefs.getBoolean("record_delivery_trips", false)
        set(v) = prefs.edit().putBoolean("record_delivery_trips", v).apply()

    val isConfigured: Boolean get() = owner.isNotBlank() && dataRepo.isNotBlank() && token.isNotBlank()
}
