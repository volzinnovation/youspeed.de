package de.youspeed.android.alpha

import android.app.Application

class YouSpeedApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        RuntimeMapDatabase.initialize(this)
        MapDataAmendmentStore.initialize(this)
    }
}
