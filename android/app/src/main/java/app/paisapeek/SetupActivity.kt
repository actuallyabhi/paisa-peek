package app.paisapeek

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

/** One field: paste the URL from More → SMS auto-capture (or just the server address). */
class SetupActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val hint = TextView(this).apply {
            text = "Paste the SMS auto-capture URL from Paisapeek → More.\n" +
                "Only the server address (https://…) also works, but then bank SMS won't be captured."
        }
        val field = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setText(Prefs.base(this@SetupActivity)?.let { b -> Prefs.token(this@SetupActivity)?.let { "$b/api/ingest/sms?token=$it" } ?: b })
        }
        val save = Button(this).apply { text = "Save" }
        val form = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
            addView(hint); addView(field); addView(save)
        }
        setContentView(FrameLayout(this).apply { addView(form) }.padForSystemBars())

        save.setOnClickListener {
            val uri = Uri.parse(field.text.toString().trim())
            if (uri.scheme !in setOf("http", "https") || uri.host.isNullOrEmpty()) {
                Toast.makeText(this, "Enter a URL starting with https://", Toast.LENGTH_LONG).show()
                return@setOnClickListener
            }
            val base = "${uri.scheme}://${uri.encodedAuthority}"
            val token = uri.getQueryParameter("token")
            Prefs.save(this, base, token)
            if (token != null) requestPermissions(arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.POST_NOTIFICATIONS), 1) else done()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) =
        done()

    private fun done() {
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP))
        finish()
    }
}
