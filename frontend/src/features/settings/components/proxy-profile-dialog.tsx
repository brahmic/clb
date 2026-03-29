import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ProxyProfile } from "@/features/proxy-profiles/schemas";

type ProxyProfileDialogProps = {
  open: boolean;
  profile: ProxyProfile | null;
  busy: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (payload: { name: string; vlessUri?: string }) => Promise<void>;
};

export function ProxyProfileDialog({ open, profile, busy, onOpenChange, onSave }: ProxyProfileDialogProps) {
  const [name, setName] = useState("");
  const [vlessUri, setVlessUri] = useState("");

  useEffect(() => {
    setName(profile?.name ?? "");
    setVlessUri("");
  }, [profile, open]);

  const canSave = name.trim().length > 0 && (profile ? true : vlessUri.trim().length > 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{profile ? "Edit proxy profile" : "Add proxy profile"}</DialogTitle>
          <DialogDescription>
            Supported: `VLESS Reality/TCP`, `VLESS WS/TLS`, and `VLESS TCP/TLS` exported from `3x-ui`.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <label className="block space-y-1">
            <span className="text-sm font-medium">Name</span>
            <Input value={name} onChange={(event) => setName(event.target.value)} disabled={busy} />
          </label>

          <label className="block space-y-1">
            <span className="text-sm font-medium">{profile ? "Replace VLESS URI" : "VLESS URI"}</span>
            <Input
              value={vlessUri}
              onChange={(event) => setVlessUri(event.target.value)}
              disabled={busy}
              placeholder="vless://..."
            />
            {profile ? (
              <p className="text-xs text-muted-foreground">Leave empty to keep the existing encrypted URI.</p>
            ) : null}
          </label>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button
            onClick={() => void onSave({ name: name.trim(), vlessUri: vlessUri.trim() || undefined })}
            disabled={busy || !canSave}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
