import { Link } from "react-router-dom";
import { Page } from "@/components/Page";

export function NotFound() {
  return (
    <Page title="Not found" description="There is no screen at this address.">
      <Link to="/" className="text-sm text-primary underline">
        Go to the overview
      </Link>
    </Page>
  );
}
