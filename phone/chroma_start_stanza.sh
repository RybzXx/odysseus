# Add this block to the existing Termux Start_All.sh.
# The literal pgrep guard also registers the service with supervise_services.sh.
# >>> odysseus-chroma
if ! pgrep -f "chroma run .*--port 8100" > /dev/null; then
    nohup proot-distro login ubuntu -- bash /root/odysseus/phone/run_chroma.sh \
        </dev/null > /data/data/com.termux/files/home/odysseus-chroma.log 2>&1 &
fi
# <<< odysseus-chroma
